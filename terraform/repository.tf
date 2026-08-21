resource "github_repository" "this" {
  name        = "caruna-ha-integration"
  description = "Home Assistant custom integration for Caruna+ metering data"
  visibility  = "public"

  has_issues      = true
  has_projects    = false
  has_wiki        = false
  has_discussions = false
  is_template     = false

  allow_merge_commit     = false
  allow_rebase_merge     = false
  allow_squash_merge     = true
  allow_auto_merge       = true
  delete_branch_on_merge = true
  allow_update_branch    = true

  squash_merge_commit_title   = "PR_TITLE"
  squash_merge_commit_message = "COMMIT_MESSAGES"

  web_commit_signoff_required = false
  archive_on_destroy          = true

  topics = [
    "caruna",
    "custom-component",
    "energy",
    "hacs",
    "home-assistant",
    "homeassistant",
    "integration",
  ]

  security_and_analysis {
    secret_scanning {
      status = "enabled"
    }

    secret_scanning_push_protection {
      status = "enabled"
    }
  }
}

resource "github_repository_vulnerability_alerts" "this" {
  repository = github_repository.this.name
  enabled    = true
}

resource "github_repository_dependabot_security_updates" "this" {
  repository = github_repository.this.name
  enabled    = true
}

resource "github_actions_repository_permissions" "this" {
  repository           = github_repository.this.name
  enabled              = true
  allowed_actions      = "all"
  sha_pinning_required = true
}

resource "github_workflow_repository_permissions" "this" {
  repository                       = github_repository.this.name
  default_workflow_permissions     = "read"
  can_approve_pull_request_reviews = false
}
