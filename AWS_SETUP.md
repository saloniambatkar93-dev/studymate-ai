# AWS Setup (only needed for AI answers and S3 storage)

> **Local mode needs none of this.** Upload, sample notes and the Retrieval test tab work with no AWS account.
>
> **What costs money:** Amazon Bedrock bills per token for every AI answer (price depends on the model:
> check the Bedrock pricing page). S3 storage/requests for a few PDFs are tiny but not necessarily free
> (free-tier rules vary by account age). Nothing is created until you run the commands below.
>
> I could not test these steps against a live AWS account while writing this guide. AWS console screens
> change, so if a menu name differs, follow the matching official AWS documentation.

## 1. Account safety (5 minutes)

1. Sign in to the AWS console and **never use the root user for daily work or create root access keys**.
2. Set a budget alert: console → **Billing and Cost Management → Budgets → Create budget → Zero spend budget** (or a $5 monthly budget).

## 2. Create a least-privilege IAM user

Console → **IAM → Policies → Create policy → JSON**. Paste this, replacing `YOUR-BUCKET-NAME` and
`YOUR_ACCOUNT_ID` (12 digits, top-right menu of the console). Name it `StudyMateAccess`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListOnlyStudyMatePrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME",
      "Condition": { "StringLike": { "s3:prefix": ["studymate/*"] } }
    },
    {
      "Sid": "ReadWriteStudyMateObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/studymate/*"
    },
    {
      "Sid": "InvokeBedrockModels",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:YOUR_ACCOUNT_ID:inference-profile/*"
      ]
    }
  ]
}
```

Tighten later by replacing `foundation-model/*` with your specific model. Then:
**IAM → Users → Create user** (name `studymate-app`, no console access) → **Attach policies directly → StudyMateAccess**
→ open the user → **Security credentials → Create access key → Command Line Interface (CLI)**.
Copy the Access key ID and Secret access key (shown once).
(If your organisation uses IAM Identity Center/SSO, use `aws configure sso` instead of access keys.)

## 3. Install the AWS CLI and sign in (Windows PowerShell)

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
```
Close and reopen PowerShell, then:
```powershell
aws --version
aws configure
```
Enter the Access key ID, Secret access key, default region `us-east-1`, output format `json`.
These are saved in `C:\Users\you\.aws\credentials`, **outside** the project, so they can't be committed.
Verify (free):
```powershell
aws sts get-caller-identity
```

## 4. Make sure a Bedrock model is available

Console → **Amazon Bedrock** (same region as `AWS_REGION`) → **Model catalog**. Pick a text model, open it,
and try it in the **Playground**. Some models ask you to submit a one-time use-case form or accept terms first;
do whatever the console asks. Copy the model's **ID** (or its inference-profile ID, such as one starting
with `us.` or `global.`) into `BEDROCK_MODEL_ID` in `.env`. If you see `AccessDenied` or `ValidationException`
errors later, the cause is almost always model access, wrong ID, or wrong region.

## 5. Create the S3 bucket (optional, only for S3 storage)

Bucket names are global, so make yours unique:
```powershell
aws s3api create-bucket --bucket studymate-yourname-20261024 --region us-east-1
aws s3api put-public-access-block --bucket studymate-yourname-20261024 --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```
For a region other than `us-east-1`, add `--create-bucket-configuration LocationConstraint=YOUR-REGION` to the first command.

## 6. Edit `.env`

```
STUDYMATE_STORAGE=s3
STUDYMATE_S3_BUCKET=studymate-yourname-20261024
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=<the model ID from step 4>
```

## 7. Check it

```powershell
python check_setup.py            # free: packages, storage, credentials
python check_setup.py --invoke   # one tiny Bedrock call (small cost)
streamlit run app.py
```

## Clean up (stop all charges)

```powershell
aws s3 rm s3://studymate-yourname-20261024 --recursive
aws s3api delete-bucket --bucket studymate-yourname-20261024
```
Then in IAM, delete the access key (and the user) when you are done.
