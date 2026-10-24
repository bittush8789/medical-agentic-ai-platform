# ==============================================================================
# Amazon Elastic Container Registry (ECR) for MedGuide Docker Images
# Features: Image Vulnerability Scanning on Push & Lifecycle Retention Rules
# ==============================================================================

resource "aws_ecr_repository" "app" {
  name                 = "medguide-ai-platform"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.environment}-medguide-ecr"
  }
}

resource "aws_ecr_lifecycle_policy" "cleanup" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain only the latest 30 release container images"
        selection = {
          tagStatus   = "any"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 30
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
