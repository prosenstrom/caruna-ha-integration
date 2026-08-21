resource "github_repository_ruleset" "require_ci" {
  name        = "Require CI"
  repository  = github_repository.this.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  bypass_actors {
    actor_id    = 5
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }

  rules {
    deletion         = true
    non_fast_forward = true

    required_status_checks {
      strict_required_status_checks_policy = true
      do_not_enforce_on_create             = true

      required_check {
        context = "ci"
      }
    }
  }
}
