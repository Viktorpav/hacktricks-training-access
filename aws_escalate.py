#!/usr/bin/env python3
from __future__ import print_function
import boto3, argparse, os, sys, json, time
from botocore.exceptions import ClientError

def main(args):
    access_key_id = args.access_key_id
    secret_access_key = args.secret_key
    session_token = args.session_token

    if args.access_key_id is None or args.secret_key is None:
        print('IAM keys not passed in as arguments, enter them below:')
        access_key_id = input('  Access Key ID: ')
        secret_access_key = input('  Secret Access Key: ')
        session_token = input('  Session Token (Leave blank if none): ')
        if session_token.strip() == '':
            session_token = None

    # Begin permissions enumeration
    current_user = None
    users = []
    client = boto3.client(
        'iam',
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token
    )
    if args.all_users is True:
        response = client.list_users()
        for user in response['Users']:
            users.append({'UserName': user['UserName'], 'Permissions': {'Allow': {}, 'Deny': {}}})
        while 'IsTruncated' in response and response['IsTruncated'] is True:
            response = client.list_users(
                Marker=response['Marker']
            )
            for user in response['Users']:
                users.append({'UserName': user['UserName'], 'Permissions': {'Allow': {}, 'Deny': {}}})
    elif args.user_name is not None:
        users.append({'UserName': args.user_name, 'Permissions': {'Allow': {}, 'Deny': {}}})
    else:
        current_user = client.get_user()['User']
        current_user = {
            'UserName': current_user['UserName'],
            'Permissions': {
                'Allow': {},
                'Deny': {}
            }
        }
        users.append(current_user)
    print('Collecting policies for {} users...'.format(len(users)))
    for user in users:
        user['Groups'] = []
        user['Policies'] = []
        try:
            policies = []

            ## Get groups that the user is in
            try:
                res = client.list_groups_for_user(
                    UserName=user['UserName']
                )
                user['Groups'] = res['Groups']
                while 'IsTruncated' in res and res['IsTruncated'] is True:
                    res = client.list_groups_for_user(
                        UserName=user['UserName'],
                        Marker=groups['Marker']
                    )
                    user['Groups'] += res['Groups']
            except Exception as e:
                print('List groups for user failed: {}'.format(e))
                user['PermissionsConfirmed'] = False

            ## Get inline and attached group policies
            for group in user['Groups']:
                group['Policies'] = []
                ## Get inline group policies
                try:
                    res = client.list_group_policies(
                        GroupName=group['GroupName']
                    )
                    policies = res['PolicyNames']
                    while 'IsTruncated' in res and res['IsTruncated'] is True:
                        res = client.list_group_policies(
                            GroupName=group['GroupName'],
                            Marker=res['Marker']
                        )
                        policies += res['PolicyNames']
                except Exception as e:
                    print('List group policies failed: {}'.format(e))
                    user['PermissionsConfirmed'] = False
                # Get document for each inline policy
                for policy in policies:
                    group['Policies'].append({ # Add policies to list of policies for this group
                        'PolicyName': policy
                    })
                    try:
                        document = client.get_group_policy(
                            GroupName=group['GroupName'],
                            PolicyName=policy
                        )['PolicyDocument']
                    except Exception as e:
                        print('Get group policy failed: {}'.format(e))
                        user['PermissionsConfirmed'] = False
                    user = parse_document(document, user)

                ## Get attached group policies
                attached_policies = []
                try:
                    res = client.list_attached_group_policies(
                        GroupName=group['GroupName']
                    )
                    attached_policies = res['AttachedPolicies']
                    while 'IsTruncated' in res and res['IsTruncated'] is True:
                        res = client.list_attached_group_policies(
                            GroupName=group['GroupName'],
                            Marker=res['Marker']
                        )
                        attached_policies += res['AttachedPolicies']
                    group['Policies'] += attached_policies
                except Exception as e:
                    print('List attached group policies failed: {}'.format(e))
                    user['PermissionsConfirmed'] = False
                user = parse_attached_policies(client, attached_policies, user)

            ## Get inline user policies
            policies = []
            if 'Policies' not in user:
                user['Policies'] = []
            try:
                res = client.list_user_policies(
                    UserName=user['UserName']
                )
                policies = res['PolicyNames']
                while 'IsTruncated' in res and res['IsTruncated'] is True:
                    res = client.list_user_policies(
                        UserName=user['UserName'],
                        Marker=res['Marker']
                    )
                    policies += res['PolicyNames']
                for policy in policies:
                    user['Policies'].append({
                        'PolicyName': policy
                    })
            except Exception as e:
                print('List user policies failed: {}'.format(e))
                user['PermissionsConfirmed'] = False
            # Get document for each inline policy
            for policy in policies:
                try:
                    document = client.get_user_policy(
                        UserName=user['UserName'],
                        PolicyName=policy
                    )['PolicyDocument']
                except Exception as e:
                    print('Get user policy failed: {}'.format(e))
                    user['PermissionsConfirmed'] = False
                user = parse_document(document, user)
            ## Get attached user policies
            attached_policies = []
            try:
                res = client.list_attached_user_policies(
                    UserName=user['UserName']
                )
                attached_policies = res['AttachedPolicies']
                while 'IsTruncated' in res and res['IsTruncated'] is True:
                    res = client.list_attached_user_policies(
                        UserName=user['UserName'],
                        Marker=res['Marker']
                    )
                    attached_policies += res['AttachedPolicies']
                user['Policies'] += attached_policies
            except Exception as e:
                print('List attached user policies failed: {}'.format(e))
                user['PermissionsConfirmed'] = False
            user = parse_attached_policies(client, attached_policies, user)
            user.pop('Groups', None)
            user.pop('Policies', None)
        except Exception as e:
            print('Error, skipping user {}:\n{}'.format(user['UserName'], e))
        print('  {}... done!'.format(user['UserName']))

    print('  Done.\n')

    # Begin privesc scanning
    all_perms = [
        'iam:AddUserToGroup',
        'iam:AttachGroupPolicy',
        'iam:AttachRolePolicy',
        'iam:AttachUserPolicy',
        'iam:CreateAccessKey',
        'iam:CreatePolicyVersion',
        'iam:CreateLoginProfile',
        'iam:PassRole',
        'iam:PutGroupPolicy',
        'iam:PutRolePolicy',
        'iam:PutUserPolicy',
        'iam:SetDefaultPolicyVersion',
        'iam:UpdateAssumeRolePolicy',
        'iam:UpdateLoginProfile',
        'sts:AssumeRole',
        'ec2:RunInstances',
        'lambda:CreateEventSourceMapping',
        'lambda:CreateFunction',
        'lambda:InvokeFunction',
        'lambda:UpdateFunctionCode',
        'dynamodb:CreateTable',
        'dynamodb:PutItem',
        'glue:CreateDevEndpoint',
        'glue:UpdateDevEndpoint',
        'cloudformation:CreateStack',
        'datapipeline:CreatePipeline'
    ]

    escalation_methods = {
        'CreateNewPolicyVersion': {
            'iam:CreatePolicyVersion': True
        },
        'SetExistingDefaultPolicyVersion': {
            'iam:SetDefaultPolicyVersion': True
        },
        'CreateEC2WithExistingIP': {
            'iam:PassRole': True,
            'ec2:RunInstances': True
        },
        'CreateAccessKey': {
            'iam:CreateAccessKey': True
        },
        'CreateLoginProfile': {
            'iam:CreateLoginProfile': True
        },
        'UpdateLoginProfile': {
            'iam:UpdateLoginProfile': True
        },
        'AttachUserPolicy': {
            'iam:AttachUserPolicy': True
        },
        'AttachGroupPolicy': {
            'iam:AttachGroupPolicy': True
        },
        'AttachRolePolicy': {
            'iam:AttachRolePolicy': True,
            'sts:AssumeRole': True
        },
        'PutUserPolicy': {
            'iam:PutUserPolicy': True
        },
        'PutGroupPolicy': {
            'iam:PutGroupPolicy': True
        },
        'PutRolePolicy': {
            'iam:PutRolePolicy': True,
            'sts:AssumeRole': True
        },
        'AddUserToGroup': {
            'iam:AddUserToGroup': True
        },
        'UpdateRolePolicyToAssumeIt': {
            'iam:UpdateAssumeRolePolicy': True,
            'sts:AssumeRole': True
        },
        'PassExistingRoleToNewLambdaThenInvoke': {
            'iam:PassRole': True,
            'lambda:CreateFunction': True,
            'lambda:InvokeFunction': True
        },
        'PassExistingRoleToNewLambdaThenTriggerWithNewDynamo': {
            'iam:PassRole': True,
            'lambda:CreateFunction': True,
            'lambda:CreateEventSourceMapping': True,
            'dynamodb:CreateTable': True,
            'dynamodb:PutItem': True
        },
        'PassExistingRoleToNewLambdaThenTriggerWithExistingDynamo': {
            'iam:PassRole': True,
            'lambda:CreateFunction': True,
            'lambda:CreateEventSourceMapping': True
        },
        'PassExistingRoleToNewGlueDevEndpoint': {
            'iam:PassRole': True,
            'glue:CreateDevEndpoint': True
        },
        'UpdateExistingGlueDevEndpoint': {
            'glue:UpdateDevEndpoint': True
        },
        'PassExistingRoleToCloudFormation': {
            'iam:PassRole': True,
            'cloudformation:CreateStack': True
        },
        'PassExistingRoleToNewDataPipeline': {
            'iam:PassRole': True,
            'datapipeline:CreatePipeline': True
        },
        'EditExistingLambdaFunctionWithRole': {
            'lambda:UpdateFunctionCode': True
        }
    }
    import re
    for user in users:
        print('User: {}'.format(user['UserName']))
        checked_perms = {'Allow': {}, 'Deny': {}}
        # Preliminary check to see if these permissions have already been enumerated in this session
        if 'Permissions' in user and 'Allow' in user['Permissions']:
            # Are they an admin already?
            if '*' in user['Permissions']['Allow'] and user['Permissions']['Allow']['*'] == ['*']:
                user['CheckedMethods'] = {'admin': {}, 'Confirmed':{}, 'Potential': {}}
                print('  Already an admin!\n')
                continue
            for perm in all_perms:
                for effect in ['Allow', 'Deny']:
                    if perm in user['Permissions'][effect]:
                        checked_perms[effect][perm] = user['Permissions'][effect][perm]
                    else:
                        for user_perm in user['Permissions'][effect].keys():
                            if '*' in user_perm:
                                pattern = re.compile(user_perm.replace('*', '.*'))
                                if pattern.search(perm) is not None:
                                    checked_perms[effect][perm] = user['Permissions'][effect][user_perm]

        checked_methods = {
            'Potential': [],
            'Confirmed': []
        }

        # Ditch each escalation method that has been confirmed not to be possible
        for method in escalation_methods:
            potential = True
            confirmed = True
            for perm in escalation_methods[method]:
                if perm not in checked_perms['Allow']: # If this permission isn't Allowed, then this method won't work
                    potential = confirmed = False
                    break
                elif perm in checked_perms['Deny'] and perm in checked_perms['Allow']: # Permission is both Denied and Allowed, leave as potential, not confirmed
                    confirmed = False
                elif perm in checked_perms['Allow'] and perm not in checked_perms['Deny']: # It is Allowed and not Denied
                    if not checked_perms['Allow'][perm] == ['*']:
                        confirmed = False
            if confirmed is True:
                print('  CONFIRMED: {}\n'.format(method))
                checked_methods['Confirmed'].append(method)
            elif potential is True:
                print('  POTENTIAL: {}\n'.format(method))
                checked_methods['Potential'].append(method)
        user['CheckedMethods'] = checked_methods
        if checked_methods['Potential'] == [] and checked_methods['Confirmed'] == []:
            print('  No methods possible.\n')

    now = time.time()
    headers = 'CreateNewPolicyVersion,SetExistingDefaultPolicyVersion,CreateEC2WithExistingIP,CreateAccessKey,CreateLoginProfile,UpdateLoginProfile,AttachUserPolicy,AttachGroupPolicy,AttachRolePolicy,PutUserPolicy,PutGroupPolicy,PutRolePolicy,AddUserToGroup,UpdateRolePolicyToAssumeIt,PassExistingRoleToNewLambdaThenInvoke,PassExistingRoleToNewLambdaThenTriggerWithNewDynamo,PassExistingRoleToNewLambdaThenTriggerWithExistingDynamo,PassExistingRoleToNewGlueDevEndpoint,UpdateExistingGlueDevEndpoint,PassExistingRoleToCloudFormation,PassExistingRoleToNewDataPipeline,EditExistingLambdaFunctionWithRole'
    file = open('all_user_privesc_scan_results_{}.csv'.format(now), 'w+')
    for user in users:
        if 'admin' in user['CheckedMethods']:
            file.write(',{} (Admin)'.format(user['UserName']))
        else:
            file.write(',{}'.format(user['UserName']))
    file.write('\n')
    for method in headers.split(','):
        file.write('{},'.format(method))
        for user in users:
            if method in user['CheckedMethods']['Confirmed']:
                file.write('Confirmed,')
            elif method in user['CheckedMethods']['Potential']:
                file.write('Potential,')
            else:
                file.write(',')
        file.write('\n')
    file.close()
    print('Privilege escalation check completed. Results stored to ./all_user_privesc_scan_results_{}.csv'.format(now))

# https://stackoverflow.com/a/24893252
def remove_empty_from_dict(d):
    if type(d) is dict:
        return dict((k, remove_empty_from_dict(v)) for k, v in d.items() if v and remove_empty_from_dict(v))
    elif type(d) is list:
        return [remove_empty_from_dict(v) for v in d if v and remove_empty_from_dict(v)]
    else:
        return d

# Pull permissions from each policy document
def parse_attached_policies(client, attached_policies, user):
    for policy in attached_policies:
        document = get_attached_policy(client, policy['PolicyArn'])
        if document is False:
            user['PermissionsConfirmed'] = False
        else:
            user = parse_document(document, user)
    return user

# Get the policy document of an attached policy
def get_attached_policy(client, policy_arn):
    try:
        policy = client.get_policy(
            PolicyArn=policy_arn
        )['Policy']
        version = policy['DefaultVersionId']
        can_get = True
    except Exception as e:
        print('Get policy failed: {}'.format(e))
        return False

    try:
        if can_get is True:
            document = client.get_policy_version(
                PolicyArn=policy_arn,
                VersionId=version
            )['PolicyVersion']['Document']
            return document
    except Exception as e:
        print('Get policy version failed: {}'.format(e))
        return False

# Loop permissions and the resources they apply to
def parse_document(document, user):
    if type(document['Statement']) is dict:
        document['Statement'] = [document['Statement']]
    for statement in document['Statement']:
        if statement['Effect'] == 'Allow':
            if 'Action' in statement and type(statement['Action']) is list: # Check if the action is a single action (str) or multiple (list)
                statement['Action'] = list(set(statement['Action'])) # Remove duplicates to stop the circular reference JSON error
                for action in statement['Action']:
                    if action in user['Permissions']['Allow']:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Allow'][action] += statement['Resource']
                        else:
                            user['Permissions']['Allow'][action].append(statement['Resource'])
                    else:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Allow'][action] = statement['Resource']
                        else:
                            user['Permissions']['Allow'][action] = [statement['Resource']]
                    user['Permissions']['Allow'][action] = list(set(user['Permissions']['Allow'][action])) # Remove duplicate resources
            elif 'Action' in statement and type(statement['Action']) is str:
                if statement['Action'] in user['Permissions']['Allow']:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Allow'][statement['Action']] += statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['Action']].append(statement['Resource'])
                else:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Allow'][statement['Action']] = statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['Action']] = [statement['Resource']] # Make sure that resources are always arrays
                user['Permissions']['Allow'][statement['Action']] = list(set(user['Permissions']['Allow'][statement['Action']])) # Remove duplicate resources
            if 'NotAction' in statement and type(statement['NotAction']) is list: # NotAction is reverse, so allowing a NotAction is denying that action basically
                statement['NotAction'] = list(set(statement['NotAction'])) # Remove duplicates to stop the circular reference JSON error
                for not_action in statement['NotAction']:
                    if not_action in user['Permissions']['Deny']:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Deny'][not_action] += statement['Resource']
                        else:
                            user['Permissions']['Deny'][not_action].append(statement['Resource'])
                    else:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Deny'][not_action] = statement['Resource']
                        else:
                            user['Permissions']['Deny'][not_action] = [statement['Resource']]
                    user['Permissions']['Deny'][not_action] = list(set(user['Permissions']['Deny'][not_action])) # Remove duplicate resources
            elif 'NotAction' in statement and type(statement['NotAction']) is str:
                if statement['NotAction'] in user['Permissions']['Deny']:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Deny'][statement['NotAction']] += statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['NotAction']].append(statement['Resource'])
                else:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Deny'][statement['NotAction']] = statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['NotAction']] = [statement['Resource']] # Make sure that resources are always arrays
                user['Permissions']['Deny'][statement['NotAction']] = list(set(user['Permissions']['Deny'][statement['NotAction']])) # Remove duplicate resources
        if statement['Effect'] == 'Deny':
            if 'Action' in statement and type(statement['Action']) is list:
                statement['Action'] = list(set(statement['Action'])) # Remove duplicates to stop the circular reference JSON error
                for action in statement['Action']:
                    if action in user['Permissions']['Deny']:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Deny'][action] += statement['Resource']
                        else:
                            user['Permissions']['Deny'][action].append(statement['Resource'])
                    else:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Deny'][action] = statement['Resource']
                        else:
                            user['Permissions']['Deny'][action] = [statement['Resource']]
                    user['Permissions']['Deny'][action] = list(set(user['Permissions']['Deny'][action])) # Remove duplicate resources
            elif 'Action' in statement and type(statement['Action']) is str:
                if statement['Action'] in user['Permissions']['Deny']:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Deny'][statement['Action']] += statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['Action']].append(statement['Resource'])
                else:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Deny'][statement['Action']] = statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['Action']] = [statement['Resource']] # Make sure that resources are always arrays
                user['Permissions']['Deny'][statement['Action']] = list(set(user['Permissions']['Deny'][statement['Action']])) # Remove duplicate resources
            if 'NotAction' in statement and type(statement['NotAction']) is list: # NotAction is reverse, so allowing a NotAction is denying that action basically
                statement['NotAction'] = list(set(statement['NotAction'])) # Remove duplicates to stop the circular reference JSON error
                for not_action in statement['NotAction']:
                    if not_action in user['Permissions']['Allow']:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Allow'][not_action] += statement['Resource']
                        else:
                            user['Permissions']['Allow'][not_action].append(statement['Resource'])
                    else:
                        if type(statement['Resource']) is list:
                            user['Permissions']['Allow'][not_action] = statement['Resource']
                        else:
                            user['Permissions']['Allow'][not_action] = [statement['Resource']]
                    user['Permissions']['Allow'][not_action] = list(set(user['Permissions']['Allow'][not_action])) # Remove duplicate resources
            elif 'NotAction' in statement and type(statement['NotAction']) is str:
                if statement['NotAction'] in user['Permissions']['Allow']:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Allow'][statement['NotAction']] += statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['NotAction']].append(statement['Resource'])
                else:
                    if type(statement['Resource']) is list:
                        user['Permissions']['Allow'][statement['NotAction']] = statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['NotAction']] = [statement['Resource']] # Make sure that resources are always arrays
                user['Permissions']['Allow'][statement['NotAction']] = list(set(user['Permissions']['Allow'][statement['NotAction']])) # Remove duplicate resources
    return user

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='This script will fetch permissions for a set of users and then scan for permission misconfigurations to see what privilege escalation methods are possible. Available attack paths will be output to a .csv file in the same directory.')
    parser.add_argument('--all-users', required=False, default=False, action='store_true', help='Run this module against every user in the account.')
    parser.add_argument('--user-name', required=False, default=None, help='A single username of a user to run this module against. By default, the user to which the active AWS keys belong to will be used.')
    parser.add_argument('--access-key-id', required=False, default=None, help='The AWS access key ID to use for authentication.')
    parser.add_argument('--secret-key', required=False, default=None, help='The AWS secret access key to use for authentication.')
    parser.add_argument('--session-token', required=False, default=None, help='The AWS session token to use for authentication, if there is one.')

    args = parser.parse_args()
    main(args)
