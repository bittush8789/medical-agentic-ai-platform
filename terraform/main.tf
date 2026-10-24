# ==============================================================================
# MedGuide AI — Production Infrastructure as Code (Terraform)
# Provisions: AWS VPC (Multi-AZ) + EKS Cluster + RDS Aurora/PostgreSQL + ElastiCache Redis
# Sized for 1 Million+ Active Users Scale
# ==============================================================================

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.45"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.29"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Production S3 Remote State Backend (uncomment and configure for cloud state)
  # backend "s3" {
  #   bucket         = "medguide-terraform-state-prod"
  #   key            = "production/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "medguide-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "MedGuide-AI-Platform"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Compliance  = "HIPAA-Eligible"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}
