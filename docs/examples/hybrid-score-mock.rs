// Standalone reproduction, not a production regression test.
// Run: rustc --test docs/examples/hybrid-score-mock.rs -o /tmp/hybrid-score-mock
//      /tmp/hybrid-score-mock --nocapture
use std::collections::{HashMap, HashSet};

#[derive(Clone)]
struct Memory {
    memory_id: &'static str,
    retrieval_score: Option<f64>,
}

#[test]
fn reproduce_fulltext_only_score_leaking_into_vector_score() {
    let vec_results = vec![
        Memory {
            memory_id: "V",
            retrieval_score: Some(0.8),
        },
        Memory {
            memory_id: "B",
            retrieval_score: Some(0.6),
        },
    ];
    let ft_results = vec![
        Memory {
            memory_id: "B",
            retrieval_score: Some(1.0),
        },
        Memory {
            memory_id: "F",
            retrieval_score: Some(2.0),
        },
    ];
    let ft_map: HashMap<_, _> = ft_results
        .iter()
        .filter_map(|m| m.retrieval_score.map(|s| (m.memory_id, s)))
        .collect();
    // Proposed fix: preserve vector-source scores before merging.
    let vec_map: HashMap<_, _> = vec_results
        .iter()
        .filter_map(|m| m.retrieval_score.map(|s| (m.memory_id, s)))
        .collect();

    // Same merge behavior as store.rs: vector object wins on duplicate IDs.
    let mut seen: HashSet<_> = vec_results.iter().map(|m| m.memory_id).collect();
    let mut candidates = vec_results;
    for m in ft_results {
        if seen.insert(m.memory_id) {
            candidates.push(m);
        }
    }

    let mut original = Vec::new();
    let mut corrected = Vec::new();
    for m in candidates {
        let old_vec = m.retrieval_score.unwrap_or(0.0); // Current implementation.
        let new_vec = vec_map.get(m.memory_id).copied().unwrap_or(0.0);
        let raw_ft = ft_map.get(m.memory_id).copied().unwrap_or(0.0);
        let kw = if raw_ft > 0.0 {
            raw_ft / (raw_ft + 1.0)
        } else {
            0.0
        };
        // All memories: observed_at=None => time=0; confidence=1; no feedback.
        let old_total = 0.3 * old_vec + 0.2 * kw + 0.3;
        let new_total = 0.3 * new_vec + 0.2 * kw + 0.3;
        println!("{}: vector {old_vec:.2} -> {new_vec:.2}, keyword={kw:.4}, total {old_total:.4} -> {new_total:.4}", m.memory_id);
        if m.memory_id == "F" {
            assert_eq!(old_vec, 2.0); // Reproduces the bug, not desired behavior.
            assert_eq!(new_vec, 0.0);
            assert!((old_total - 1.0333333333333333).abs() < 1e-12);
            assert!((new_total - 0.4333333333333333).abs() < 1e-12);
        } else {
            assert_eq!(old_total, new_total); // Other sources stay unchanged.
        }
        original.push((m.memory_id, old_total));
        corrected.push((m.memory_id, new_total));
    }
    original.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    corrected.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    let old_ids: Vec<_> = original.iter().map(|m| m.0).collect();
    let new_ids: Vec<_> = corrected.iter().map(|m| m.0).collect();
    assert_eq!(old_ids, ["F", "B", "V"]);
    assert_eq!(new_ids, ["B", "V", "F"]);
    println!("Top 2: {:?} -> {:?}", &old_ids[..2], &new_ids[..2]);
}
