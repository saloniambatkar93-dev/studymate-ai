"""Turn confusing AWS / boto3 errors into short, beginner-friendly messages."""
from __future__ import annotations


def _explain_one(exc: BaseException) -> str | None:
    name = type(exc).__name__

    # Errors returned by an AWS service (S3, Bedrock, ...)
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and "Error" in response:
        err = response["Error"]
        code = err.get("Code", "Unknown")
        detail = err.get("Message", "")
        if code == "NoSuchBucket":
            return "The S3 bucket does not exist. Check STUDYMATE_S3_BUCKET in your .env file."
        if code in {"AccessDenied", "AccessDeniedException"}:
            return (
                "AWS denied access. Your IAM user/role may be missing a permission "
                "(S3 or Bedrock), or Bedrock model access is not enabled for this model "
                "in this region. See AWS_SETUP.md. "
                f"Details: {detail}"
            )
        if code in {"ExpiredToken", "ExpiredTokenException", "RequestExpired"}:
            return "Your AWS credentials have expired. Refresh them (for SSO: 'aws sso login') and try again."
        if code in {"InvalidAccessKeyId", "UnrecognizedClientException", "SignatureDoesNotMatch",
                    "InvalidSignatureException", "InvalidClientTokenId"}:
            return "Your AWS credentials look invalid. Re-run 'aws configure' with a valid access key."
        if code in {"ThrottlingException", "TooManyRequestsException", "SlowDown",
                    "ServiceQuotaExceededException"}:
            return "AWS is rate-limiting requests right now. Wait a few seconds and try again."
        if code in {"ResourceNotFoundException", "ValidationException"}:
            return (
                "Amazon Bedrock rejected the request. The model ID may be wrong, not available in "
                "your region, or may need an inference-profile ID. Check BEDROCK_MODEL_ID and "
                f"AWS_REGION in .env. Details: {detail}"
            )
        if code in {"ModelNotReadyException", "ServiceUnavailableException",
                    "InternalServerException", "ModelTimeoutException"}:
            return "The AWS service is temporarily unavailable. Please try again in a moment."
        return f"AWS error ({code}): {detail}"

    # Errors raised by boto3/botocore before a request is even answered
    if name in {"NoCredentialsError", "PartialCredentialsError"}:
        return (
            "AWS credentials were not found. Run 'aws configure' (see AWS_SETUP.md), or use "
            "local mode which needs no AWS account."
        )
    if name == "NoRegionError":
        return "No AWS region is set. Add AWS_REGION=us-east-1 to your .env file."
    if name == "ProfileNotFound":
        return "The AWS profile named in AWS_PROFILE does not exist. Check your .env file."
    if name in {"EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError",
                "ConnectionClosedError"}:
        return "Could not reach AWS. Check your internet connection and AWS_REGION, then try again."
    if name in {"TokenRetrievalError", "SSOTokenLoadError", "UnauthorizedSSOTokenError"}:
        return "Your AWS SSO login has expired. Run 'aws sso login' and try again."
    return None


def friendly_aws_message(exc: BaseException) -> str | None:
    """Return a friendly message if `exc` (or what caused it) is a known AWS problem."""
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 6:
        message = _explain_one(current)
        if message:
            return message
        current = current.__cause__ or current.__context__
        seen += 1
    return None
