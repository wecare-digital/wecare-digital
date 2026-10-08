#!/usr/bin/env python3
"""Create the coupon Lambda from a validated package; default is dry run.

Existing functions are never overwritten. Subsequent updates use the ordinary
reviewed deployment/version/alias path. Credentials remain runtime references.
"""
import argparse
import boto3
from botocore.exceptions import ClientError
from deploy_all_lambdas import SPECS, build_zip, validate, validate_handler

ACCOUNT = '775261844268'
REGION = 'us-east-1'
FUNCTION = 'wecare-coupons'
ROLE = f'arn:aws:iam::{ACCOUNT}:role/wecare-coupons-role'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    session = boto3.Session(profile_name='wecare-prod', region_name=REGION)
    assert session.client('sts').get_caller_identity()['Account'] == ACCOUNT
    lam = session.client('lambda')
    spec = next(s for s in SPECS if s.name == FUNCTION)
    blob, members = build_zip(spec)
    errors, warnings = validate(spec, members, frozenset())
    errors += validate_handler(members, 'handler.handler')
    if errors:
        raise RuntimeError('Coupon package failed validation: ' + '; '.join(errors))
    try:
        lam.get_function_configuration(FunctionName=FUNCTION)
    except ClientError as error:
        if error.response['Error']['Code'] != 'ResourceNotFoundException':
            raise
    else:
        print('Function already exists; use the reviewed update path.')
        return
    print(f'Validated {len(members)} package files; warnings: {warnings}')
    if not args.apply:
        print('Dry run: would create coupon function and live alias.')
        return
    created = lam.create_function(
        FunctionName=FUNCTION, Runtime='python3.12', Role=ROLE,
        Handler='handler.handler', Code={'ZipFile': blob}, Publish=True,
        Timeout=30, MemorySize=256, Architectures=['x86_64'],
        Description='Authenticated coupon issuance and customer eligibility',
        Tags={'Project': 'WECARE.DIGITAL', 'Purpose': 'Coupons'},
    )
    lam.get_waiter('function_active_v2').wait(
        FunctionName=FUNCTION, WaiterConfig={'Delay': 2, 'MaxAttempts': 60})
    lam.create_alias(FunctionName=FUNCTION, Name='live',
                     FunctionVersion=created['Version'],
                     Description='Verified coupon service')
    live = lam.get_function_configuration(FunctionName=FUNCTION, Qualifier='live')
    assert live['State'] == 'Active' and live['CodeSha256'] == created['CodeSha256']
    print(f"Coupon live version {live['Version']} verified.")


if __name__ == '__main__':
    main()
