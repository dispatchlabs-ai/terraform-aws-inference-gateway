# Contributing

This is a maintainer-led MIT source alpha by Chris Reynolds. Contributions use
MIT without a CLA or copyright assignment. Keep public examples synthetic and
keep runtime provider logic in Dispatch's inference-gateway package.

Install OpenTofu or Terraform and run:

```sh
tofu fmt -check -recursive
tofu init -backend=false
tofu validate
tofu -chdir=examples/basic init -backend=false
tofu -chdir=examples/basic validate
python3 -m py_compile lambda/stopped.py
git diff --check
```

A successful validation is not an AWS deployment acceptance. Document real
provisioning, authenticated inference, rotation, takeover and teardown evidence
separately. Never validate recovery by running two OAuth writers. Review changes
to table identity, lifecycle, IAM, task stopping or receipt conditions closely.
Keep a clean clone usable without private infrastructure. No GitHub Actions are
configured; checks run locally. Report defects with metadata-only reproduction
steps, versions and expected behavior, excluding secrets and inference content.
