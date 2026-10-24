variable "aws_region" {
  description = "Target AWS deployment region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "Base CIDR block for the AWS Virtual Private Cloud"
  type        = string
  default     = "10.0.0.0/16"
}

variable "cluster_name" {
  description = "Name of the AWS EKS managed Kubernetes cluster"
  type        = string
  default     = "medguide-prod-eks"
}

variable "kubernetes_version" {
  description = "Desired Kubernetes control plane version"
  type        = string
  default     = "1.30"
}

variable "eks_node_instance_types" {
  description = "EC2 instance types for the EKS managed node group"
  type        = list(string)
  default     = ["m6i.xlarge", "m5.xlarge"]
}

variable "eks_min_nodes" {
  description = "Minimum number of worker nodes (idle / low traffic)"
  type        = number
  default     = 3
}

variable "eks_desired_nodes" {
  description = "Standard operating capacity of worker nodes"
  type        = number
  default     = 5
}

variable "eks_max_nodes" {
  description = "Maximum autoscaling capacity of worker nodes for 1M user traffic spikes"
  type        = number
  default     = 50
}

# ── RDS PostgreSQL Variables ──

variable "db_name" {
  description = "PostgreSQL production database name"
  type        = string
  default     = "medguide_production"
}

variable "db_username" {
  description = "Master administrative username for PostgreSQL"
  type        = string
  default     = "medguide_admin"
}

variable "db_instance_class" {
  description = "Instance type for RDS PostgreSQL Multi-AZ deployment"
  type        = string
  default     = "db.r6g.xlarge"
}

variable "db_allocated_storage" {
  description = "Initial storage allocation in GB"
  type        = number
  default     = 100
}

variable "db_max_allocated_storage" {
  description = "Autoscaling storage ceiling in GB for high-volume audit/memory growth"
  type        = number
  default     = 1000
}

# ── ElastiCache Redis Variables ──

variable "redis_node_type" {
  description = "Instance type for AWS ElastiCache Redis cluster"
  type        = string
  default     = "cache.m6g.large"
}

variable "redis_num_shards" {
  description = "Number of shards for Redis cluster mode"
  type        = number
  default     = 3
}
