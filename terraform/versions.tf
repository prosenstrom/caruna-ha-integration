# GitHub settings for prosenstrom/caruna-ha-integration.
# Auth: export GITHUB_TOKEN with repo admin (gh auth token).
# First apply imports the live repo via imports.tf.

terraform {
  required_version = ">= 1.8.0"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.13"
    }
  }
}

provider "github" {
  owner = "prosenstrom"
}
