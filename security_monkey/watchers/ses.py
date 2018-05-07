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
.. module: security_monkey.watchers.ses
    :platform: Unix

.. version:: $$VERSION$$
.. moduleauthor:: Patrick Kelley <pkelley@netflix.com> @monkeysecurity

"""

from security_monkey.watcher import Watcher
from security_monkey.watcher import ChangeItem
from security_monkey.constants import TROUBLE_REGIONS
from security_monkey.exceptions import BotoConnectionIssue
from security_monkey import app

from boto.ses import regions


class SES(Watcher):
    index = 'ses'
    i_am_singular = 'SES Identity'
    i_am_plural = 'SES Identities'

    def __init__(self, accounts=None, debug=False):
        super(SES, self).__init__(accounts=accounts, debug=debug)

    def slurp(self):
        """
        :returns: item_list - list of SES Identities.
        :returns: exception_map - A dict where the keys are a tuple containing the
            location of the exception and the value is the actual exception

        """
        self.prep_for_slurp()
        from security_monkey.common.sts_connect import connect
        item_list = []
        exception_map = {}
        for account in self.accounts:
            for region in regions():

                if region.name == 'eu-central-1':
                    # as of boto 2.34.0, boto cannot connect to ses in eu-central-1
                    # TODO: Remove this if-block when boto can handle ses in eu-central-1
                    continue

                app.logger.debug("Checking {}/{}/{}".format(self.index, account, region.name))
                try:
                    ses = connect(account, 'ses', region=region.name)
                    response = self.wrap_aws_rate_limited_call(
                        ses.list_identities
                    )
                    identities = response.Identities

                    domains = []
                    verified_domains = []
                    for identity in identities:
                        if not "@" in identity:
                            domains.append(identity)

                    if len(domains) > 0:
                        response = self.wrap_aws_rate_limited_call(
                            ses.get_identity_verification_attributes,
                            domains
                        )

                        results = response.GetIdentityVerificationAttributesResponse.GetIdentityVerificationAttributesResult.VerificationAttributes
                        for result in results:
                            if result.value.VerificationStatus == 'Success':
                                verified_domains.append(result.key)

                    response = self.wrap_aws_rate_limited_call(
                        ses.list_verified_email_addresses
                    )
                    verified_identities = response.VerifiedEmailAddresses
                    verified_identities += verified_domains
                except Exception as e:
                    if region.name not in TROUBLE_REGIONS:
                        exc = BotoConnectionIssue(str(e), self.index, account, region.name)
                        self.slurp_exception((self.index, account, region.name), exc, exception_map,
                                             source="{}-watcher".format(self.index))
                    continue
                app.logger.debug("Found {} {}. {} are verified.".format(len(identities), self.i_am_plural,
                                                                        len(verified_identities)))
                for identity in identities:
                    if self.check_ignore_list(identity):
                        continue
                    
                    config = {
                        'name': identity,
                        'verified': identity in verified_identities
                    }

                    item = SESItem(region=region.name, account=account, name=identity, config=dict(config),
                                   source_watcher=self)
                    item_list.append(item)

        return item_list, exception_map


class SESItem(ChangeItem):
    def __init__(self, region=None, account=None, name=None, config=None, source_watcher=None):
        super(SESItem, self).__init__(
            index=SES.index,
            region=region,
            account=account,
            name=name,
            new_config=config if config else {},
            source_watcher=source_watcher)
