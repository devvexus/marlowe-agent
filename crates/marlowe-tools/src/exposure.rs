//! CONTRACTS.md §7.2 — registration ≠ exposure.
//!
//! > **INVARIANT: returns <= 12. Enforced by the type's constructor, not by convention.**
//!
//! HP10 makes this one of four budget tests that fail the build. The mechanism is the
//! constructor: [`ExposedSet`] has a private field and no way in except [`ExposedSet::new`],
//! so "≤12" is a property of every value that exists rather than a property of the call sites
//! somebody remembered to check.
//!
//! Serde routes through the same constructor. A deserialization path that built the struct
//! field-wise would be a thirteenth tool arriving from a config file, and the assertion would
//! still be present and still pass.

use serde::{Deserialize, Serialize};

use crate::manifest::ToolId;

/// ARCHITECTURE §5: eleven tools, one slot spare. The spare is deliberate — it is what lets a
/// profile add one situational tool without a redesign, and it is not a place to put a
/// twelfth permanent tool.
pub const MAX_EXPOSED_TOOLS: usize = 12;

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ExposureError {
    #[error(
        "a capability profile exposed {got} tools; the budget is {MAX_EXPOSED_TOOLS} \
         (ARCHITECTURE §5, HP10). Registration is unlimited — expose fewer and let the model \
         reach the rest through `use`"
    )]
    TooMany { got: usize },

    #[error(
        "tool `{tool}` is exposed twice. Two slots spent on one tool is a budget that counts \
         wrong, and the duplicate would be invisible in the model's tool list"
    )]
    Duplicate { tool: ToolId },
}

/// The model-visible tool set for one run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct ExposedSet {
    tools: Vec<ToolId>,
}

impl ExposedSet {
    /// The only constructor. Rejects an over-budget set and a set with duplicates.
    pub fn new(tools: Vec<ToolId>) -> Result<Self, ExposureError> {
        if tools.len() > MAX_EXPOSED_TOOLS {
            return Err(ExposureError::TooMany { got: tools.len() });
        }
        for (i, t) in tools.iter().enumerate() {
            if tools[..i].contains(t) {
                return Err(ExposureError::Duplicate { tool: t.clone() });
            }
        }
        Ok(Self { tools })
    }

    /// The quarantined reader's set (§8.2). Named rather than written as `new(vec![])` at each
    /// call site, because "empty" is the security property and it should be greppable.
    pub fn empty() -> Self {
        Self { tools: Vec::new() }
    }

    pub fn len(&self) -> usize {
        self.tools.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    pub fn contains(&self, tool: &ToolId) -> bool {
        self.tools.contains(tool)
    }

    pub fn iter(&self) -> impl Iterator<Item = &ToolId> {
        self.tools.iter()
    }

    pub fn as_slice(&self) -> &[ToolId] {
        &self.tools
    }
}

impl<'de> Deserialize<'de> for ExposedSet {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let tools = Vec::<ToolId>::deserialize(d)?;
        Self::new(tools).map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(n: usize) -> Vec<ToolId> {
        (0..n).map(|i| ToolId::new(format!("t{i}"))).collect()
    }

    #[test]
    fn twelve_is_allowed_and_thirteen_is_not() {
        assert!(ExposedSet::new(ids(MAX_EXPOSED_TOOLS)).is_ok());
        assert_eq!(
            ExposedSet::new(ids(MAX_EXPOSED_TOOLS + 1)),
            Err(ExposureError::TooMany { got: 13 })
        );
    }

    #[test]
    fn duplicates_are_refused() {
        let dup = vec![ToolId::new("read"), ToolId::new("read")];
        assert_eq!(
            ExposedSet::new(dup),
            Err(ExposureError::Duplicate { tool: ToolId::new("read") })
        );
    }

    #[test]
    fn deserialization_runs_the_same_constructor() {
        // A thirteenth tool arriving from a config file must be refused by the same code the
        // constructor uses. Without this the invariant would hold everywhere except the one
        // path that reads user input.
        let thirteen = serde_json::to_string(&ids(13)).unwrap();
        assert!(serde_json::from_str::<ExposedSet>(&thirteen).is_err());

        let twelve = serde_json::to_string(&ids(12)).unwrap();
        assert_eq!(serde_json::from_str::<ExposedSet>(&twelve).unwrap().len(), 12);
    }
}
