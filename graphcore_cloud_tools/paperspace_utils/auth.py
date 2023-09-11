# Copyright (c) 2023 Graphcore Ltd. All rights reserved.

# Internal documentation available here:
# https://graphcore.atlassian.net/wiki/spaces/PM/pages/3323920580/Credential+handling+for+S3+Paperspace+production+service
AWS_CREDENTIAL_ENV_VAR = "DATASET_S3_DOWNLOAD_B64_CREDENTIAL"
DEFAULT_S3_CREDENTIAL = """W2djZGF0YS1yXQphd3NfYWNjZXNzX2tleV9pZCA9IDc0Q0QwUVVHVkEwUVo3WUZSSlhSCmF3c19zZWNyZXRf
YWNjZXNzX2tleSA9IExDZENYMEs1aW1USUZRTkVZQzVnY3VkT2prWlFmcHkxZ0p4VjN1RkwK"""

if __name__ == "__main__":
    print(DEFAULT_S3_CREDENTIAL.replace("\n", ""))
