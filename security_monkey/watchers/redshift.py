#     Copyright 2014 Yelp, Inc.
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
.. module: security_monkey.watchers.redshift
    :platform: Unix

.. version:: $$VERSION$$
.. moduleauthor:: Ivan Leichtling <ivanlei@yelp.com> @c0wl

"""

from security_monkey.watcher import Watcher
from security_monkey.watcher import ChangeItem
from security_monkey.constants import TROUBLE_REGIONS
from security_monkey.exceptions import BotoConnectionIssue
from security_monkey.datastore import Account
from security_monkey import app, ARN_PREFIX

from boto.redshift import regions


class Redshift(Watcher):
    index = 'redshift'
    i_am_singular = 'Redshift Cluster'
    i_am_plural = 'Redshift Clusters'

    def __init__(self, accounts=None, debug=False):
        super(Redshift, self).__init__(accounts=accounts, debug=debug)
        self.honor_ephemerals = True
        self.ephemeral_paths = [
            "RestoreStatus",
            "ClusterStatus",
            "ClusterParameterGroups$ParameterApplyStatus",
            "ClusterParameterGroups$ClusterParameterStatusList$ParameterApplyErrorDescription",
            "ClusterParameterGroups$ClusterParameterStatusList$ParameterApplyStatus",
            "ClusterRevisionNumber"
        ]

    def slurp(self):
        """
        :returns: item_list - list of Redshift Policies.
        :returns: exception_map - A dict where the keys are a tuple containing the
            location of the exception and the value is the actual exception

        """
        self.prep_for_slurp()
        from security_monkey.common.sts_connect import connect
        item_list = []
        exception_map = {}
        for account in self.accounts:
            account_db = Account.query.filter(Account.name == account).first()
            account_number = account_db.identifier

            for region in regions():
                app.logger.debug("Checking {}/{}/{}".format(self.index, account, region.name))
                try:
                    redshift = connect(account, 'redshift', region=region)

                    all_clusters = []
                    marker = None
                    while True:
                        response = self.wrap_aws_rate_limited_call(
                            redshift.describe_clusters,
                            marker=marker
                        )
                        all_clusters.extend(response['DescribeClustersResponse']['DescribeClustersResult']['Clusters'])
                        if response['DescribeClustersResponse']['DescribeClustersResult']['Marker'] is not None:
                            marker = response['DescribeClustersResponse']['DescribeClustersResult']['Marker']
                        else:
                            break

                except Exception as e:
                    if region.name not in TROUBLE_REGIONS:
                        exc = BotoConnectionIssue(str(e), 'redshift', account, region.name)
                        self.slurp_exception((self.index, account, region.name), exc, exception_map,
                                             source="{}-watcher".format(self.index))
                    continue
                app.logger.debug("Found {} {}".format(len(all_clusters), Redshift.i_am_plural))
                for cluster in all_clusters:
                    cluster_id = cluster['ClusterIdentifier']
                    if self.check_ignore_list(cluster_id):
                        continue

                    arn = ARN_PREFIX + ':redshift:{region}:{account_number}:cluster:{name}'.format(
                        region=region.name,
                        account_number=account_number,
                        name=cluster_id)

                    cluster['arn'] = arn

                    item = RedshiftCluster(region=region.name, account=account, name=cluster_id, arn=arn,
                                           config=dict(cluster), source_watcher=self)
                    item_list.append(item)

        return item_list, exception_map


class RedshiftCluster(ChangeItem):
    def __init__(self, region=None, account=None, name=None, arn=None, config=None, source_watcher=None):
        super(RedshiftCluster, self).__init__(
            index=Redshift.index,
            region=region,
            account=account,
            name=name,
            arn=arn,
            new_config=config if config else {},
            source_watcher=source_watcher)
