resource "aws_dynamodb_table" "access" {
  count        = var.enable_employee_access ? 1 : 0
  name         = "${var.name}-access"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  ttl {
    attribute_name = "expires"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  deletion_protection_enabled = true
  tags                        = var.tags
  lifecycle { prevent_destroy = true }
}
