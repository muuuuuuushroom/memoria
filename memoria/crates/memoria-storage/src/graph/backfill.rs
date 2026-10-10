//! Build graph nodes + association edges + entity links from existing memories.
//! Equivalent to Python's ActivationIndexManager.backfill().

use crate::graph::ner;
use crate::graph::types::{GraphNode, NodeType};
use crate::store::SqlMemoryStore;
use memoria_core::MemoriaError;
use std::collections::{HashMap, HashSet};
use std::future::Future;
use uuid::Uuid;

#[derive(Debug, Default)]
pub struct BackfillResult {
    pub processed: usize,
    pub skipped: usize,
    pub edges_created: usize,
    pub entities_linked: usize,
}

#[derive(Clone, Default)]
struct EntityPlan {
    // First occurrence wins, matching sequential INSERT-on-duplicate behavior.
    entities: Vec<(String, String, String)>,
    links: Vec<(String, String)>, // memory_id, normalized entity name
    unstorable_entities: usize,
}

fn plan_entities(
    memories: impl IntoIterator<Item = (String, Vec<ner::ExtractedEntity>)>,
) -> EntityPlan {
    let mut plan = EntityPlan::default();
    let mut names = HashSet::new();
    let mut links = HashSet::new();
    for (memory_id, entities) in memories {
        for entity in entities {
            let name = entity.name.to_lowercase();
            // mem_entities uses VARCHAR(200) for name/display and VARCHAR(20)
            // for type. INSERT IGNORE can truncate invalid input, so filter it
            // before deduplication or ID resolution; never link a truncated name.
            // The old per-entity INSERT rejected these rows and continued.
            if name.chars().count() > 200
                || entity.name.chars().count() > 200
                || entity.entity_type.chars().count() > 20
            {
                plan.unstorable_entities += 1;
                continue;
            }
            if names.insert(name.clone()) {
                // The old backfill uses entity.name, rather than entity.display.
                plan.entities
                    .push((name.clone(), entity.name, entity.entity_type));
            }
            if links.insert((memory_id.clone(), name.clone())) {
                plan.links.push((memory_id.clone(), name));
            }
        }
    }
    plan
}

async fn persist_entity_plan<U, UF, L, LF>(
    plan: EntityPlan,
    upsert_entities: U,
    upsert_links: L,
) -> Result<usize, MemoriaError>
where
    U: FnOnce(Vec<(String, String, String)>) -> UF,
    UF: Future<Output = Result<Vec<(String, String)>, MemoriaError>>,
    L: FnOnce(Vec<(String, String)>) -> LF,
    LF: Future<Output = Result<(), MemoriaError>>,
{
    if plan.entities.is_empty() {
        return Ok(0);
    }
    let ids: HashMap<_, _> = upsert_entities(plan.entities).await?.into_iter().collect();
    let links: Vec<_> = plan
        .links
        .into_iter()
        .map(|(memory, name)| {
            ids.get(&name)
                .cloned()
                .map(|id| (memory, id))
                .ok_or_else(|| {
                    MemoriaError::Database(format!("backfill entity ID missing: {name}"))
                })
        })
        .collect::<Result<_, _>>()?;
    let count = links.len();
    upsert_links(links).await?;
    Ok(count)
}

/// Build graph from all active memories for a user.
/// Idempotent — skips memories that already have graph nodes.
pub async fn backfill_graph(
    sql: &SqlMemoryStore,
    user_id: &str,
) -> Result<BackfillResult, MemoriaError> {
    let mut result = BackfillResult::default();
    let graph = sql.graph_store();
    let table = sql.active_table(user_id).await?;
    let memories = sql.list_active_from(&table, user_id, 500).await?;

    let mut pending = Vec::new();
    for mem in &memories {
        if graph.get_node_by_memory_id(&mem.memory_id).await?.is_some() {
            result.skipped += 1;
            continue;
        }
        pending.push(mem);
    }

    let plan = plan_entities(
        pending
            .iter()
            .map(|mem| (mem.memory_id.clone(), ner::extract_entities(&mem.content))),
    );
    if plan.unstorable_entities > 0 {
        tracing::warn!(
            user_id,
            unstorable_entities = plan.unstorable_entities,
            "backfill skipped entities exceeding mem_entities character limits"
        );
    }
    let graph = &graph;
    result.entities_linked = persist_entity_plan(
        plan,
        |entities| async move {
            let refs: Vec<_> = entities
                .iter()
                .map(|(name, display, kind)| (name.as_str(), display.as_str(), kind.as_str()))
                .collect();
            graph.batch_upsert_entities(user_id, &refs).await
        },
        |links| async move {
            let refs: Vec<_> = links
                .iter()
                .map(|(memory, entity)| (memory.as_str(), entity.as_str(), "ner"))
                .collect();
            graph.batch_upsert_memory_entity_links(user_id, &refs).await
        },
    )
    .await?;

    // Nodes mark completion: create them only after all entity/link writes succeed.
    // A partial write can then be retried without skipping unfinished memories.
    for mem in pending {
        let importance = if mem.initial_confidence >= 0.85 {
            0.6
        } else {
            0.5
        };
        let node = GraphNode {
            node_id: Uuid::new_v4().simple().to_string(),
            user_id: user_id.to_string(),
            node_type: NodeType::Semantic,
            content: mem.content.clone(),
            entity_type: None,
            embedding: mem.embedding.clone(),
            memory_id: Some(mem.memory_id.clone()),
            session_id: mem.session_id.clone(),
            confidence: mem.initial_confidence as f32,
            trust_tier: mem.trust_tier.to_string(),
            importance,
            source_nodes: vec![],
            conflicts_with: None,
            conflict_resolution: None,
            access_count: 0,
            cross_session_count: 0,
            is_active: true,
            superseded_by: None,
            created_at: mem.observed_at.map(|dt| dt.naive_utc()),
        };
        graph.create_node(&node).await?;
        result.processed += 1;
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};
    use std::future::ready;

    fn entity(name: &str, kind: &str) -> ner::ExtractedEntity {
        ner::ExtractedEntity {
            name: name.into(),
            display: "unused original display".into(),
            entity_type: kind.into(),
        }
    }

    fn duplicate_plan() -> EntityPlan {
        plan_entities([
            (
                "m1".into(),
                vec![entity("Rust", "tech"), entity("RUST", "person")],
            ),
            (
                "m2".into(),
                vec![entity("rust", "concept"), entity("Python", "tech")],
            ),
        ])
    }

    #[test]
    fn entity_plan_keeps_first_metadata_and_all_memory_links() {
        let plan = duplicate_plan();
        assert_eq!(
            plan.entities,
            vec![
                ("rust".into(), "Rust".into(), "tech".into()),
                ("python".into(), "Python".into(), "tech".into()),
            ]
        );
        assert_eq!(
            plan.links,
            vec![
                ("m1".into(), "rust".into()),
                ("m2".into(), "rust".into()),
                ("m2".into(), "python".into()),
            ]
        );
    }

    #[test]
    fn rule_ner_plan_matches_sequential_entity_and_link_sets() {
        let inputs = [
            (
                "m1".to_string(),
                ner::extract_entities("Rust Python GitHub MyProject"),
            ),
            (
                "m2".to_string(),
                ner::extract_entities("RUST python GitHub MyProject"),
            ),
        ];
        let mut expected_entities = HashMap::new();
        let mut expected_links = HashSet::new();
        for (memory, entities) in &inputs {
            for entity in entities {
                let name = entity.name.to_lowercase();
                expected_entities
                    .entry(name.clone())
                    .or_insert((entity.name.clone(), entity.entity_type.clone()));
                expected_links.insert((memory.clone(), name));
            }
        }
        let plan = plan_entities(inputs);
        assert!(!plan.entities.is_empty());
        let actual_entities: HashMap<_, _> = plan
            .entities
            .into_iter()
            .map(|(name, display, kind)| (name, (display, kind)))
            .collect();
        assert_eq!(actual_entities, expected_entities);
        assert_eq!(
            plan.links.into_iter().collect::<HashSet<_>>(),
            expected_links
        );
    }

    #[test]
    fn long_data_uri_entity_does_not_discard_valid_memory_links() {
        let text = format!(
            "Rust Python Example](data:image/png;base64,{})",
            "A".repeat(640)
        );
        let entities = ner::extract_entities(&text);
        assert!(entities
            .iter()
            .any(|entity| entity.name.chars().count() > 200));
        let expected: Vec<_> = entities
            .iter()
            .filter(|entity| {
                entity.name.to_lowercase().chars().count() <= 200
                    && entity.name.chars().count() <= 200
                    && entity.entity_type.chars().count() <= 20
            })
            .map(|entity| {
                (
                    entity.name.to_lowercase(),
                    entity.name.clone(),
                    entity.entity_type.clone(),
                )
            })
            .collect();
        let plan = plan_entities([("m1".into(), entities)]);
        assert!(plan.unstorable_entities > 0);
        assert_eq!(plan.entities, expected);
        assert!(plan.links.contains(&("m1".into(), "rust".into())));
        assert!(plan.links.contains(&("m1".into(), "python".into())));
        assert!(plan
            .links
            .iter()
            .all(|(_, name)| !name.contains("data:image")));
    }

    #[test]
    fn entity_character_limits_keep_unicode_boundaries_without_truncation() {
        let boundary = "界".repeat(200);
        let overflow = "界".repeat(201);
        let type_boundary = "类".repeat(20);
        let plan = plan_entities([(
            "m1".into(),
            vec![
                entity(&boundary, &type_boundary),
                entity(&overflow, "tech"),
                entity("valid-name", &"类".repeat(21)),
                // Lowercasing can expand the character count: 100 dotted I's
                // normalize to 200 characters, whereas 101 normalize to 202.
                entity(&"İ".repeat(100), "tech"),
                entity(&"İ".repeat(101), "tech"),
            ],
        )]);
        assert_eq!(plan.unstorable_entities, 3);
        assert_eq!(
            plan.entities,
            vec![
                (boundary.clone(), boundary.clone(), type_boundary),
                ("i\u{307}".repeat(100), "İ".repeat(100), "tech".into()),
            ]
        );
        assert_eq!(plan.links.len(), 2);
    }

    #[test]
    fn invalid_first_type_does_not_hide_later_storable_duplicate() {
        let plan = plan_entities([(
            "m1".into(),
            vec![entity("Rust", &"t".repeat(21)), entity("RUST", "tech")],
        )]);
        assert_eq!(plan.unstorable_entities, 1);
        assert_eq!(
            plan.entities,
            vec![("rust".into(), "RUST".into(), "tech".into())]
        );
        assert_eq!(plan.links, vec![("m1".into(), "rust".into())]);
    }

    #[tokio::test]
    async fn entity_write_failure_propagates_before_links_and_retry_resolves_existing_ids() {
        let links_called = Cell::new(false);
        let error = persist_entity_plan(
            duplicate_plan(),
            |_| ready(Err(MemoriaError::Database("entity batch failed".into()))),
            |_| {
                links_called.set(true);
                ready(Ok(()))
            },
        )
        .await
        .unwrap_err();
        assert!(error.to_string().contains("entity batch failed"));
        assert!(!links_called.get());

        let links = RefCell::new(Vec::new());
        let count = persist_entity_plan(
            duplicate_plan(),
            |_| {
                ready(Ok(vec![
                    ("rust".into(), "existing-rust".into()),
                    ("python".into(), "new-python".into()),
                ]))
            },
            |rows| {
                *links.borrow_mut() = rows;
                ready(Ok(()))
            },
        )
        .await
        .unwrap();
        assert_eq!(count, 3);
        assert_eq!(
            *links.borrow(),
            vec![
                ("m1".into(), "existing-rust".into()),
                ("m2".into(), "existing-rust".into()),
                ("m2".into(), "new-python".into()),
            ]
        );
    }

    #[tokio::test]
    async fn link_write_failure_propagates_and_retry_is_idempotent() {
        let attempts = RefCell::new(Vec::new());
        for fail in [true, false] {
            let result = persist_entity_plan(
                duplicate_plan(),
                |_| {
                    ready(Ok(vec![
                        ("rust".into(), "r".into()),
                        ("python".into(), "p".into()),
                    ]))
                },
                |rows| {
                    attempts.borrow_mut().push(rows);
                    ready(if fail {
                        Err(MemoriaError::Database("link batch failed".into()))
                    } else {
                        Ok(())
                    })
                },
            )
            .await;
            if fail {
                assert!(result
                    .unwrap_err()
                    .to_string()
                    .contains("link batch failed"));
            } else {
                assert_eq!(result.unwrap(), 3);
            }
        }
        assert_eq!(attempts.borrow()[0], attempts.borrow()[1]);
    }

    #[tokio::test]
    async fn incomplete_entity_resolution_fails_before_link_writes() {
        let links_called = Cell::new(false);
        let result = persist_entity_plan(
            duplicate_plan(),
            |_| ready(Ok(vec![("rust".into(), "r".into())])),
            |_| {
                links_called.set(true);
                ready(Ok(()))
            },
        )
        .await;
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("entity ID missing: python"));
        assert!(!links_called.get());
    }
}
