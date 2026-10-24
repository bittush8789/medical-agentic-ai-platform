output "vpc_id" {
  description = "ID of the provisioned VPC"
  value       = aws_vpc.main.id
}

output "eks_cluster_name" {
  description = "EKS cluster identifier"
  value       = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  description = "Kubernetes API server endpoint"
  value       = aws_eks_cluster.main.endpoint
}

output "eks_cluster_certificate_authority_data" {
  description = "Base64 encoded certificate data required to communicate with the cluster"
  value       = aws_eks_cluster.main.certificate_authority[0].data
  sensitive   = true
}

output "rds_postgres_endpoint" {
  description = "Primary connection endpoint for AWS RDS PostgreSQL"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_postgres_address" {
  description = "Hostname of the RDS PostgreSQL instance"
  value       = aws_db_instance.postgres.address
}

output "rds_database_name" {
  description = "Database name"
  value       = aws_db_instance.postgres.db_name
}

output "elasticache_redis_endpoint" {
  description = "Primary cluster configuration endpoint for AWS ElastiCache Redis"
  value       = aws_elasticache_replication_group.redis.configuration_endpoint_address
}

output "ecr_repository_url" {
  description = "Docker image repository URL in Amazon ECR"
  value       = aws_ecr_repository.app.repository_url
}
