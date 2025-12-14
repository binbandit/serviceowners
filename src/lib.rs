use anyhow::{Context, Result};
use globset::{GlobBuilder, GlobSet, GlobSetBuilder};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Represents the content of services.yaml
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ServicesFile {
    pub services: HashMap<String, ServiceDef>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ServiceDef {
    pub owners: Option<Vec<Owner>>,
    pub contact: Option<Contact>,
    pub docs: Option<String>,
    pub runbook: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(untagged)]
pub enum Owner {
    Team { team: String },
    User { user: String },
    Email { email: String },
    // Fallback for simple strings if any
    Raw(String),
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Contact {
    pub slack: Option<String>,
    pub email: Option<String>,
}

/// A match explanation
#[derive(Debug)]
pub struct ExplainMatch<'a> {
    pub service: &'a str,
    pub pattern: String,
}

/// Core mapper that resolves paths to services
pub struct ServiceMapper {
    glob_set: GlobSet,
    /// Maps glob index to service name
    service_names: Vec<String>,
    /// Maps glob index to the original pattern (for explanation)
    pub patterns: Vec<String>,
}

impl ServiceMapper {
    pub fn from_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read SERVICEOWNERS file at {:?}", path))?;
        Self::parse(&content)
    }

    pub fn parse(content: &str) -> Result<Self> {
        let mut builder = GlobSetBuilder::new();
        let mut service_names = Vec::new();
        let mut patterns = Vec::new();

        for (line_idx, line) in content.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }

            // Format: "pattern    service"
            let split_once: Vec<&str> = line.splitn(2, |c: char| c.is_whitespace()).collect();
            if split_once.len() < 2 {
                anyhow::bail!(
                    "Invalid line {}: '{}' - expected 'pattern service'",
                    line_idx + 1,
                    line
                );
            }
            let raw_pattern = split_once[0];
            let service = split_once[1].trim();

            let glob_str = normalize_pattern(raw_pattern)?;
            let glob = GlobBuilder::new(&glob_str)
                .literal_separator(true) // match / as separator
                .build()
                .with_context(|| {
                    format!(
                        "Invalid glob pattern on line {}: {}",
                        line_idx + 1,
                        raw_pattern
                    )
                })?;

            builder.add(glob);
            service_names.push(service.to_string());
            patterns.push(raw_pattern.to_string());
        }

        let glob_set = builder.build().context("Failed to build glob set")?;
        Ok(Self {
            glob_set,
            service_names,
            patterns,
        })
    }

    pub fn find_service(&self, path: &str) -> Option<&str> {
        let matches = self.glob_set.matches(path);
        matches
            .iter()
            .max()
            .map(|idx| self.service_names[*idx].as_str())
    }

    pub fn explain_service(&self, path: &str) -> Vec<ExplainMatch<'_>> {
        let matches = self.glob_set.matches(path);
        let mut result = Vec::new();
        for idx in matches {
            result.push(ExplainMatch {
                service: &self.service_names[idx],
                pattern: self.patterns[idx].clone(),
            });
        }
        result
    }
}

pub fn normalize_pattern(pat: &str) -> Result<String> {
    // 1. strip
    let mut s = pat.trim().to_string();
    if s.is_empty() {
        return Ok(s);
    }

    // 2. replace backslash
    s = s.replace('\\', "/");

    // 3. strip leading ./
    while s.starts_with("./") {
        s = s[2..].to_string();
    }

    // 4. strip leading / (anchor to root is implied by 'contains slash' logic + absolute match)
    if s.starts_with('/') {
        s = s[1..].to_string();
    }

    // 5. trailing slash => /**
    if s.ends_with('/') {
        if s == "/" {
            return Ok("**".to_string());
        }
        s.pop(); // remove /
        s.push_str("/**");
    }

    // 6. If no slash, prepend **/
    if !s.contains('/') {
        s = format!("**/{}", s);
    }

    Ok(s)
}

/// Heuristics for Init command
pub fn init_from_codeowners(codeowners_path: &Path) -> Result<String> {
    let content = fs::read_to_string(codeowners_path)
        .with_context(|| format!("Failed to read CODEOWNERS at {:?}", codeowners_path))?;

    let mut out = String::new();
    out.push_str("# Generated from CODEOWNERS by serviceowners (init)\n");
    out.push_str("# pattern            service\n");

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }

        let pattern = parts[0];
        let owners = &parts[1..];

        let service = infer_service_name(pattern, owners);
        out.push_str(&format!("{:<20} {}\n", pattern, service));
    }
    Ok(out)
}

fn infer_service_name(pattern: &str, owners: &[&str]) -> String {
    let p = pattern.trim_start_matches('/').trim_end_matches('/');
    let segments: Vec<&str> = p.split('/').collect();

    let candidates: Vec<&str> = segments
        .iter()
        .filter(|&&s| {
            s != "*" && s != "**" && s != "src" && s != "lib" && s != "packages" && s != "apps"
        })
        .cloned()
        .collect();

    if let Some(last) = candidates.last() {
        let name = last.replace(|c: char| !c.is_alphanumeric(), "_");
        if !name.is_empty() {
            return name.to_lowercase();
        }
    }

    if let Some(owner) = owners.first() {
        let o = owner.trim_start_matches('@');
        if let Some((_, name)) = o.split_once('/') {
            return name.replace('-', "_").to_lowercase();
        }
        return o.replace('-', "_").to_lowercase();
    }

    "unknown_service".to_string()
}
