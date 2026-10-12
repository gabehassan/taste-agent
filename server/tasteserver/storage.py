import boto3
from botocore.config import Config

from .config import S3_ACCESS_KEY, S3_BUCKET, S3_ENDPOINT, S3_REGION, S3_SECRET_KEY

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT or None,
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY or None,
            aws_secret_access_key=S3_SECRET_KEY or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _client


def put(key, data, content_type="application/octet-stream"):
    client().put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)
    return key


def get(key):
    return client().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def delete(key):
    client().delete_object(Bucket=S3_BUCKET, Key=key)


def presign(key, seconds=900):
    return client().generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=seconds)


def usage():
    total, n = 0, 0
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET):
        for o in page.get("Contents", []):
            total += o["Size"]
            n += 1
    return {"bytes": total, "objects": n}
