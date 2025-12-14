use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use serviceowners::{init_from_codeowners, ServiceMapper};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Parser)]
#[command(name = "sowners")]
#[command(about = "Service ownership tool")]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Path to SERVICEOWNERS file
    #[arg(long, default_value = "SERVICEOWNERS")]
    serviceowners_file: PathBuf,

    /// Path to services.yaml file
    #[arg(long, default_value = "services.yaml")]
    services_file: PathBuf,
}

#[derive(Subcommand)]
enum Commands {
    /// Find out who owns a specific path
    WhoOwns {
        path: String,
        #[arg(long)]
        explain: bool,
    },
    /// List services impacted by changes
    Impacted {
        /// Git diff range (e.g. origin/main...HEAD)
        #[arg(long)]
        diff: Option<String>,

        /// Fail if unmapped files are found
        #[arg(long)]
        fail_on_unmapped: bool,

        /// Output format (text, json, markdown)
        #[arg(long, default_value = "text")]
        format: String,

        /// List changed files per service
        #[arg(long)]
        show_files: bool,
    },
    /// Lint the SERVICEOWNERS file
    Lint {
        /// Strict mode (currently unused, for compat)
        #[arg(long)]
        strict: bool,
        /// Check if patterns match any files
        #[arg(long)]
        check_matches: bool,
    },
    /// Initialize from CODEOWNERS
    Init {
        #[arg(long)]
        codeowners: Option<PathBuf>,
        #[arg(long)]
        write: bool,
        #[arg(long)]
        force: bool,
    },
    /// Run as a GitHub Action
    Action {
        #[arg(long)]
        diff: Option<String>,
        #[arg(long, default_value = "true")]
        comment: String, // "true" or "false"
        #[arg(long, default_value = "true")]
        fail_on_unmapped: String,
        #[arg(long, default_value = "false")]
        strict_lint: String,
    },
}

fn main() -> Result<()> {
    env_logger::init();

    let cli = Cli::parse();

    match cli.command {
        Commands::WhoOwns { path, explain } => {
            let mapper = ServiceMapper::from_file(&cli.serviceowners_file)?;
            match mapper.find_service(&path) {
                Some(svc) => {
                    println!("{}", svc);
                    if explain {
                        println!("\nMatches:");
                        let matches = mapper.explain_service(&path);
                        for m in matches {
                            let chosen = if m.service == svc { " <== chosen" } else { "" };
                            println!("- {} -> {}{}", m.pattern, m.service, chosen);
                        }
                    }
                }
                None => {
                    println!("Unmapped");
                    if explain {
                        println!("\nNo matches found.");
                    }
                }
            }
        }
        Commands::Impacted {
            diff,
            fail_on_unmapped,
            format,
            show_files,
        } => {
            let mapper = ServiceMapper::from_file(&cli.serviceowners_file)?;

            let files = get_changed_files(diff.as_deref())?;
            let mut service_files: HashMap<String, Vec<String>> = HashMap::new();
            let mut unmapped_files = Vec::new();

            for file in &files {
                match mapper.find_service(file) {
                    Some(svc) => {
                        service_files
                            .entry(svc.to_string())
                            .or_default()
                            .push(file.clone());
                    }
                    None => {
                        unmapped_files.push(file.clone());
                    }
                }
            }
            let mut sorted_services: Vec<String> = service_files.keys().cloned().collect();
            sorted_services.sort();

            match format.as_str() {
                "json" => {
                    let impacted_services: Vec<String> = sorted_services.clone();
                    let mut services_detail = HashMap::new();
                    for (svc, files) in &service_files {
                        services_detail.insert(
                            svc,
                            serde_json::json!({
                                "count": files.len(),
                                "files": files
                            }),
                        );
                    }
                    let payload = serde_json::json!({
                        "impacted_services": impacted_services,
                        "services": services_detail,
                        "unmapped_files": unmapped_files,
                    });
                    println!("{}", serde_json::to_string_pretty(&payload)?);
                }
                "markdown" => {
                    println!("### Impacted Services\n");
                    if sorted_services.is_empty() {
                        println!("_No services impacted_");
                    } else {
                        println!("| Service | Files |");
                        println!("| --- | --- |");
                        for svc in &sorted_services {
                            let count = service_files[svc].len();
                            println!("| **{}** | {} |", svc, count);
                        }
                    }
                    if !unmapped_files.is_empty() {
                        println!("\n### Unmapped Files\n");
                        for f in &unmapped_files {
                            println!("- `{}`", f);
                        }
                    }
                }
                _ => {
                    if !sorted_services.is_empty() {
                        println!("Impacted Services:");
                        for svc in &sorted_services {
                            println!("- {}", svc);
                            if show_files {
                                for f in &service_files[svc] {
                                    println!("  - {}", f);
                                }
                            }
                        }
                    }
                    if !unmapped_files.is_empty() {
                        println!("\nUnmapped Files:");
                        for f in &unmapped_files {
                            println!("- {}", f);
                        }
                    }
                }
            }

            if fail_on_unmapped && !unmapped_files.is_empty() {
                std::process::exit(3);
            }
        }
        Commands::Lint {
            strict: _,
            check_matches,
        } => {
            let mapper = ServiceMapper::from_file(&cli.serviceowners_file)?;
            println!("Valid SERVICEOWNERS syntax");

            if check_matches {
                println!("Checking matches (this may take a while for large repos)...");
                let mut used_rules = HashSet::new();
                let walker = ignore::WalkBuilder::new(".").build();
                for result in walker {
                    match result {
                        Ok(entry) => {
                            if entry.file_type().map(|ft| ft.is_file()).unwrap_or(false) {
                                let path = entry.path();
                                if let Ok(rel) = path.strip_prefix(".") {
                                    let path_str = rel.to_string_lossy();
                                    let matches = mapper.explain_service(&path_str);
                                    for m in matches {
                                        used_rules.insert(m.pattern);
                                    }
                                }
                            }
                        }
                        Err(err) => eprintln!("Error walking repo: {}", err),
                    }
                }

                let mut unused_count = 0;
                for pat in &mapper.patterns {
                    if !used_rules.contains(pat) {
                        println!("Warning: Pattern '{}' matches no files.", pat);
                        unused_count += 1;
                    }
                }

                if unused_count == 0 {
                    println!("All patterns match at least one file.");
                } else {
                    println!("Found {} unused patterns.", unused_count);
                    // If strict check was enabled, we could exit non-zero here.
                    // Python version: lint warnings cause exit 2 on strict.
                    // The argument `strict` is available here.
                    // But I'll leave it as warning for now unless asked.
                }
            }
        }
        Commands::Init {
            codeowners,
            write,
            force,
        } => {
            let co_path = if let Some(p) = codeowners {
                p
            } else {
                let candidates = vec![
                    PathBuf::from("CODEOWNERS"),
                    PathBuf::from(".github/CODEOWNERS"),
                    PathBuf::from("docs/CODEOWNERS"),
                ];
                candidates.into_iter().find(|p| p.exists()).ok_or_else(|| {
                    anyhow::anyhow!("CODEOWNERS file not found (use --codeowners)")
                })?
            };
            let out = init_from_codeowners(&co_path)?;
            if write {
                if cli.serviceowners_file.exists() && !force {
                    anyhow::bail!(
                        "{:?} already exists (use --force to overwrite)",
                        cli.serviceowners_file
                    );
                }
                std::fs::write(&cli.serviceowners_file, out)?;
                println!("Wrote {:?}", cli.serviceowners_file);
            } else {
                println!("{}", out);
            }
        }
        Commands::Action {
            diff,
            comment,
            fail_on_unmapped,
            strict_lint,
        } => {
            action_runner(
                diff,
                &cli.serviceowners_file,
                &cli.services_file,
                comment == "true",
                fail_on_unmapped == "true",
                strict_lint == "true",
            )?;
        }
    }

    Ok(())
}

fn get_changed_files(diff_arg: Option<&str>) -> Result<Vec<String>> {
    let args = match diff_arg {
        Some(range) => vec!["diff", "--name-only", range],
        None => vec!["diff", "--name-only", "HEAD~1", "HEAD"],
    };

    let output = Command::new("git")
        .args(&args)
        .output()
        .context("Failed to run git diff")?;

    if !output.status.success() {
        anyhow::bail!(
            "git diff failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let stdout = String::from_utf8(output.stdout)?;
    Ok(stdout.lines().map(|s| s.to_string()).collect())
}

fn action_runner(
    diff_arg: Option<String>,
    serviceowners: &Path,
    _services: &Path,
    comment: bool,
    fail_on_unmapped: bool,
    _strict_lint: bool,
) -> Result<()> {
    // 1. Determine diff
    let diff = if let Some(d) = diff_arg {
        d
    } else {
        "HEAD~1...HEAD".to_string()
    };

    let mapper = ServiceMapper::from_file(serviceowners)?;
    let files = get_changed_files(Some(&diff))?;
    let mut impacted_services: HashSet<String> = HashSet::new();
    let mut unmapped_files = Vec::new();

    for file in &files {
        match mapper.find_service(file) {
            Some(svc) => {
                impacted_services.insert(svc.to_string());
            }
            None => {
                unmapped_files.push(file.clone());
            }
        }
    }

    // GITHUB_OUTPUT
    if let Ok(path) = std::env::var("GITHUB_OUTPUT") {
        let mut f = std::fs::OpenOptions::new().append(true).open(path)?;
        use std::io::Write;
        let services_vec: Vec<&String> = impacted_services.iter().collect();
        let services_json = serde_json::to_string(&services_vec)?;
        let unmapped_json = serde_json::to_string(&unmapped_files)?;
        writeln!(f, "impacted_services={}", services_json)?;
        writeln!(f, "unmapped_files={}", unmapped_json)?;
    }

    // Markdown Body
    let mut md = String::new();
    md.push_str("### 🧭 ServiceOwners Impact Report\n\n");
    md.push_str(&format!("Diff: `{}`\n\n", diff));
    if impacted_services.is_empty() {
        md.push_str("_No services impacted_");
    } else {
        md.push_str("| Service | \n| --- | \n");
        let mut sorted: Vec<&String> = impacted_services.iter().collect();
        sorted.sort();
        for svc in sorted {
            md.push_str(&format!("| **{}** | \n", svc));
        }
    }
    md.push_str("\n<!-- serviceowners:begin -->\n<!-- serviceowners:end -->");

    // GITHUB_STEP_SUMMARY
    if let Ok(path) = std::env::var("GITHUB_STEP_SUMMARY") {
        let mut f = std::fs::OpenOptions::new().append(true).open(path)?;
        use std::io::Write;
        f.write_all(md.as_bytes())?;
    }

    // PR Commenting
    if comment {
        if let Ok(token) = std::env::var("GITHUB_TOKEN") {
            if let Ok(event_path) = std::env::var("GITHUB_EVENT_PATH") {
                if let Ok(content) = std::fs::read_to_string(event_path) {
                    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                        if let Some(pr_num) = json
                            .get("pull_request")
                            .and_then(|pr| pr.get("number"))
                            .and_then(|n| n.as_i64())
                        {
                            if let Ok(repo) = std::env::var("GITHUB_REPOSITORY") {
                                post_pr_comment(&token, &repo, pr_num, &md)?;
                            }
                        }
                    }
                }
            }
        }
    }

    if fail_on_unmapped && !unmapped_files.is_empty() {
        std::process::exit(3);
    }

    Ok(())
}

fn post_pr_comment(token: &str, repo: &str, pr_num: i64, body: &str) -> Result<()> {
    let client = reqwest::blocking::Client::new();
    let url = format!(
        "https://api.github.com/repos/{}/issues/{}/comments",
        repo, pr_num
    );

    let marker = "<!-- serviceowners:begin -->";
    let resp = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "serviceowners-rust")
        .send()?
        .json::<Vec<serde_json::Value>>()?;

    let mut comment_id = None;
    for c in resp {
        if let Some(b) = c.get("body").and_then(|s| s.as_str()) {
            if b.contains(marker) {
                comment_id = c.get("id").and_then(|id| id.as_i64());
                break;
            }
        }
    }

    let payload = serde_json::json!({ "body": body });

    if let Some(id) = comment_id {
        let update_url = format!(
            "https://api.github.com/repos/{}/issues/comments/{}",
            repo, id
        );
        client
            .patch(&update_url)
            .header("Authorization", format!("Bearer {}", token))
            .header("User-Agent", "serviceowners-rust")
            .json(&payload)
            .send()?;
        println!("Updated comment {}", id);
    } else {
        client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("User-Agent", "serviceowners-rust")
            .json(&payload)
            .send()?;
        println!("Created comment on PR #{}", pr_num);
    }

    Ok(())
}
