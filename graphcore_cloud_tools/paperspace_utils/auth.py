# Copyright (c) 2023 Graphcore Ltd. All rights reserved.

AWS_CREDENTIAL_ENV_VAR = "DATASET_S3_DOWNLOAD_B64_CREDENTIAL"  # See confluence
DEFAULT_S3_CREDENTIAL = """W2djZGF0YS1yXQphd3NfYWNjZXNzX2tleV9pZCA9IDc0Q0QwUVVHVkEwUVo3WUZSSlhSCmF3c19zZWNyZXRf
YWNjZXNzX2tleSA9IExDZENYMEs1aW1USUZRTkVZQzVnY3VkT2prWlFmcHkxZ0p4VjN1RkwK"""

if __name__ == "__main__":
    print(DEFAULT_S3_CREDENTIAL)