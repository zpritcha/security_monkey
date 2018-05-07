#     Copyright 2014 Netflix, Inc.
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
"""
.. module: security_monkey.watchers.iam.iam_group
    :platform: Unix

.. version:: $$VERSION$$
.. moduleauthor:: Patrick Kelley <pkelley@netflix.com> @monkeysecurity

"""

from security_monkey.watcher import Watcher
from security_monkey.watcher import ChangeItem
from security_monkey.exceptions import InvalidAWSJSON
from security_monkey.exceptions import BotoConnectionIssue
from security_monkey import app

import json
import urllib


def all_managed_policies(conn):
    managed_policies = {}

    for policy in conn.policies.all():
        for attached_group in policy.attached_groups.all():
            policy_dict = {
                "name": policy.policy_name,
                "arn": policy.arn,
                "version": policy.default_version_id
            }

            if attached_group.arn not in managed_policies:
                managed_policies[attached_group.arn] = [policy_dict]
            else:
                managed_policies[attached_group.arn].append(policy_dict)

    return managed_policies


class IAMGroup(Watcher):
    index = 'iamgroup'
    i_am_singular = 'IAM Group'
    i_am_plural = 'IAM Groups'

    def __init__(self, accounts=None, debug=False):
        super(IAMGroup, self).__init__(accounts=accounts, debug=debug)

    def get_all_groups(self, conn):
        all_groups = []
        marker = None

        while True:
            groups_response = self.wrap_aws_rate_limited_call(
                conn.get_all_groups,
                marker=marker
            )

            all_groups.extend(groups_response.groups)
            if hasattr(groups_response, 'marker'):
                marker = groups_response.marker
            else:
                break

        return all_groups

    def get_all_group_policies(self, conn, group_name):
        all_group_policies = []
        marker = None

        while True:
            group_policies = self.wrap_aws_rate_limited_call(
                conn.get_all_group_policies,
                group_name,
                marker=marker
            )

            all_group_policies.extend(group_policies.policy_names)
            if hasattr(group_policies, 'marker'):
                marker = group_policies.marker
            else:
                break

        return all_group_policies

    def get_all_group_users(self, conn, group_name):
        all_group_users = []
        marker = None

        while True:
            group_users_response = self.wrap_aws_rate_limited_call(
                conn.get_group,
                group_name,
                marker=marker
            )

            all_group_users.extend(group_users_response.users)
            if hasattr(group_users_response, 'marker'):
                marker = group_users_response.marker
            else:
                break

        return all_group_users

    def slurp(self):
        """
        :returns: item_list - list of IAM Groups.
        :returns: exception_map - A dict where the keys are a tuple containing the
            location of the exception and the value is the actual exception
        """
        self.prep_for_slurp()
        item_list = []
        exception_map = {}

        from security_monkey.common.sts_connect import connect
        for account in self.accounts:

            try:
                boto3_iam_resource = connect(account, 'boto3.iam.resource')
                managed_policies = all_managed_policies(boto3_iam_resource)

                iam = connect(account, 'iam')
                groups = self.get_all_groups(iam)
            except Exception as e:
                exc = BotoConnectionIssue(str(e), 'iamgroup', account, None)
                self.slurp_exception((self.index, account, 'universal'), exc, exception_map,
                                     source="{}-watcher".format(self.index))
                continue

            for group in groups:
                app.logger.debug("Slurping %s (%s) from %s" % (self.i_am_singular, group.group_name, account))

                if self.check_ignore_list(group.group_name):
                    continue

                item_config = {
                    'group': dict(group),
                    'grouppolicies': {},
                    'users': {}
                }

                if group.arn in managed_policies:
                    item_config['managed_policies'] = managed_policies.get(group.arn)

                ### GROUP POLICIES ###
                group_policies = self.get_all_group_policies(iam, group.group_name)

                for policy_name in group_policies:
                    policy = self.wrap_aws_rate_limited_call(iam.get_group_policy, group.group_name, policy_name)
                    policy = policy.policy_document
                    policy = urllib.unquote(policy)
                    try:
                        policydict = json.loads(policy)
                    except:
                        exc = InvalidAWSJSON(policy)
                        self.slurp_exception((self.index, account, 'universal', group.group_name), exc, exception_map,
                                             source="{}-watcher".format(self.index))

                    item_config['grouppolicies'][policy_name] = dict(policydict)

                ### GROUP USERS ###
                group_users = self.get_all_group_users(iam, group['group_name'])
                for user in group_users:
                    item_config['users'][user.arn] = user.user_name

                item = IAMGroupItem(account=account, name=group.group_name, config=item_config,
                                    arn=item_config.get('group', {}).get('arn'), source_watcher=self)
                item_list.append(item)

        return item_list, exception_map


class IAMGroupItem(ChangeItem):
    def __init__(self, account=None, name=None, arn=None, config=None, source_watcher=None):
        super(IAMGroupItem, self).__init__(
            index=IAMGroup.index,
            region='universal',
            account=account,
            name=name,
            arn=arn,
            new_config=config if config else {},
            source_watcher=source_watcher)
