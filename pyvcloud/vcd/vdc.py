# VMware vCloud Director Python SDK
# Copyright (c) 2014 VMware, Inc. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from lxml import etree
from pyvcloud.vcd.client import E
from pyvcloud.vcd.client import E_OVF
from pyvcloud.vcd.client import EntityType
from pyvcloud.vcd.client import find_link
from pyvcloud.vcd.client import NSMAP
from pyvcloud.vcd.client import RelationType
from pyvcloud.vcd.org import Org
from pyvcloud.vcd.utils import access_control_settings_to_dict
from pyvcloud.vcd.utils import get_admin_href


class VDC(object):
    def __init__(self, client, name=None, href=None, resource=None):
        self.client = client
        self.name = name
        self.href = href
        self.resource = resource
        if resource is not None:
            self.name = resource.get('name')
            self.href = resource.get('href')
        self.href_admin = get_admin_href(self.href)

    def get_resource(self):
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)
        return self.resource

    def get_resource_href(self, name, entity_type=EntityType.VAPP):
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)
        result = []
        if hasattr(self.resource, 'ResourceEntities') and \
           hasattr(self.resource.ResourceEntities, 'ResourceEntity'):
            for vapp in self.resource.ResourceEntities.ResourceEntity:
                if entity_type is None or \
                   entity_type.value == vapp.get('type'):
                    if vapp.get('name') == name:
                        result.append(vapp.get('href'))
        if len(result) == 0:
            raise Exception('not found')
        elif len(result) > 1:
            raise Exception('more than one found, use the vapp-id')
        return result[0]

    def reload(self):
        self.resource = self.client.get_resource(self.href)
        if self.resource is not None:
            self.name = self.resource.get('name')
            self.href = self.resource.get('href')

    def get_vapp(self, name):
        return self.client.get_resource(self.get_resource_href(name))

    def delete_vapp(self, name, force=False):
        href = self.get_resource_href(name)
        return self.client.delete_resource(href, force)

    # NOQA refer to http://pubs.vmware.com/vcd-820/index.jsp?topic=%2Fcom.vmware.vcloud.api.sp.doc_27_0%2FGUID-BF9B790D-512E-4EA1-99E8-6826D4B8E6DC.html
    def instantiate_vapp(self,
                         name,
                         catalog,
                         template,
                         network=None,
                         fence_mode='bridged',
                         ip_allocation_mode='dhcp',
                         deploy=True,
                         power_on=True,
                         accept_all_eulas=False,
                         memory=None,
                         cpu=None,
                         disk_size=None,
                         password=None,
                         cust_script=None,
                         vm_name=None,
                         hostname=None,
                         storage_profile=None):
        """
        Instantiate a vApp from a vApp template in a catalog.
        If customization parameters are provided, it will customize the VM and guest OS, taking some assumptions.
        See each parameter for details.

        :param name: (str): The name of the new vApp.
        :param catalog: (str): The name of the catalog.
        :param template: (str): The name of the vApp template.
        :param network: (str): The name of a VDC network.
            When provided, connects the VM to the network.
            It assumes one VM in the vApp and one NIC in the VM.
        :param fence_mode: (str): Fence mode.
            Possible values are `bridged` and `natRouted`
        :param ip_allocation_mode: (str): IP allocation mode.
            Possible values are `pool`, `dhcp` and `static`
        :param deploy: (bool):
        :param power_on: (bool):
        :param accept_all_eulas: (bool): True confirms acceptance of all EULAs in a vApp template.
        :param memory: (int):
        :param cpu: (int):
        :param disk_size: (int):
        :param password: (str):
        :param cust_script: (str):
        :param vm_name: (str): When provided, set the name of the VM.
            It assumes one VM in the vApp.
        :param hostname: (str): When provided, set the hostname of the guest os.
            It assumes one VM in the vApp.
        :param storage_profile: (str):

        :return:  A :class:`lxml.objectify.StringElement` object describing the new vApp.
        """  # NOQA

        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        # Get hold of the template
        org_href = find_link(self.resource, RelationType.UP,
                             EntityType.ORG.value).href
        org = Org(self.client, href=org_href)
        catalog_item = org.get_catalog_item(catalog, template)
        template_resource = self.client.get_resource(
            catalog_item.Entity.get('href'))

        # If network is not specified by user then default to
        # vApp network name specified in the template
        template_networks = template_resource.xpath(
            '//ovf:NetworkSection/ovf:Network',
            namespaces={
                'ovf': NSMAP['ovf']
            })
        assert len(template_networks) > 0
        network_name_from_template = template_networks[0].get(
            '{' + NSMAP['ovf'] + '}name')
        if ((network is None) and (network_name_from_template != 'none')):
            network = network_name_from_template

        # Find the network in vdc referred to by user, using
        # name of the network
        network_href = network_name = None
        if network is not None:
            if hasattr(self.resource, 'AvailableNetworks') and \
               hasattr(self.resource.AvailableNetworks, 'Network'):
                for n in self.resource.AvailableNetworks.Network:
                    if network == n.get('name'):
                        network_href = n.get('href')
                        network_name = n.get('name')
                        break
            if network_href is None:
                raise Exception(
                    'Network \'%s\' not found in the Virtual Datacenter.' %
                    network)

        # Configure the network of the vApp
        vapp_instantiation_param = None
        if network_name is not None:
            network_configuration = E.Configuration(
                E.ParentNetwork(href=network_href), E.FenceMode(fence_mode))

            if fence_mode == 'natRouted':
                # TODO(need to find the vm_id)
                vm_id = None
                network_configuration.append(
                    E.Features(
                        E.NatService(
                            E.IsEnabled('true'), E.NatType('ipTranslation'),
                            E.Policy('allowTraffic'),
                            E.NatRule(
                                E.OneToOneVmRule(
                                    E.MappingMode('automatic'),
                                    E.VAppScopedVmId(vm_id), E.VmNicId(0))))))

            vapp_instantiation_param = E.InstantiationParams(
                E.NetworkConfigSection(
                    E_OVF.Info('Configuration for logical networks'),
                    E.NetworkConfig(
                        network_configuration, networkName=network_name)))

        # Get all vms in the vapp template
        vms = template_resource.xpath(
            '//vcloud:VAppTemplate/vcloud:Children/vcloud:Vm',
            namespaces=NSMAP)
        assert len(vms) > 0

        vm_instantiation_param = E.InstantiationParams()

        # Configure network of the first vm
        if network_name is not None:
            primary_index = int(vms[
                0].NetworkConnectionSection.PrimaryNetworkConnectionIndex.text)
            vm_instantiation_param.append(
                E.NetworkConnectionSection(
                    E_OVF.Info(
                        'Specifies the available VM network connections'),
                    E.NetworkConnection(
                        E.NetworkConnectionIndex(primary_index),
                        E.IsConnected('true'),
                        E.IpAddressAllocationMode(ip_allocation_mode.upper()),
                        network=network_name)))

        # Configure cpu, memory, disk of the first vm
        cpu_params = memory_params = disk_params = None
        if memory is not None or cpu is not None or disk_size is not None:
            virtual_hardware_section = E_OVF.VirtualHardwareSection(
                E_OVF.Info('Virtual hardware requirements'))
            items = vms[0].xpath(
                '//ovf:VirtualHardwareSection/ovf:Item',
                namespaces={
                    'ovf': NSMAP['ovf']
                })
            for item in items:
                if memory is not None and memory_params is None:
                    if item['{' + NSMAP['rasd'] + '}ResourceType'] == 4:
                        item['{' + NSMAP['rasd'] +
                             '}ElementName'] = '%s MB of memory' % memory
                        item['{' + NSMAP['rasd'] + '}VirtualQuantity'] = memory
                        memory_params = item
                        virtual_hardware_section.append(memory_params)

                if cpu is not None and cpu_params is None:
                    if item['{' + NSMAP['rasd'] + '}ResourceType'] == 3:
                        item['{' + NSMAP['rasd'] +
                             '}ElementName'] = '%s virtual CPU(s)' % cpu
                        item['{' + NSMAP['rasd'] + '}VirtualQuantity'] = cpu
                        cpu_params = item
                        virtual_hardware_section.append(cpu_params)

                if disk_size is not None and disk_params is None:
                    if item['{' + NSMAP['rasd'] + '}ResourceType'] == 17:
                        item['{' + NSMAP['rasd'] + '}Parent'] = None
                        item['{' + NSMAP['rasd'] + '}HostResource'].attrib[
                            '{' + NSMAP['vcloud'] +
                            '}capacity'] = '%s' % disk_size
                        item['{' + NSMAP['rasd'] +
                             '}VirtualQuantity'] = disk_size * 1024 * 1024
                        disk_params = item
                        virtual_hardware_section.append(disk_params)
            vm_instantiation_param.append(virtual_hardware_section)

        # Configure guest customization for the vm
        if password is not None or cust_script is not None or \
           hostname is not None:
            guest_customization_param = E.GuestCustomizationSection(
                E_OVF.Info('Specifies Guest OS Customization Settings'),
                E.Enabled('true'),
            )
            if password is None:
                guest_customization_param.append(
                    E.AdminPasswordEnabled('false'))
            else:
                guest_customization_param.append(
                    E.AdminPasswordEnabled('true'))
                guest_customization_param.append(E.AdminPasswordAuto('false'))
                guest_customization_param.append(E.AdminPassword(password))
                guest_customization_param.append(
                    E.ResetPasswordRequired('false'))
            if cust_script is not None:
                guest_customization_param.append(
                    E.CustomizationScript(cust_script))
            if hostname is not None:
                guest_customization_param.append(E.ComputerName(hostname))
            vm_instantiation_param.append(guest_customization_param)

        # Craft the <SourcedItem> element for the first VM
        sourced_item = E.SourcedItem(
            E.Source(
                href=vms[0].get('href'),
                id=vms[0].get('id'),
                name=vms[0].get('name'),
                type=vms[0].get('type')))

        vm_general_params = E.VmGeneralParams()
        if vm_name is not None:
            vm_general_params.append(E.Name(vm_name))

        # TODO(check if it needs customization if network, cpu or memory...)
        if disk_size is None and \
           password is None and \
           cust_script is None and \
           hostname is None:
            needs_customization = 'false'
        else:
            needs_customization = 'true'
        vm_general_params.append(E.NeedsCustomization(needs_customization))
        sourced_item.append(vm_general_params)
        sourced_item.append(vm_instantiation_param)

        if storage_profile is not None:
            sp = self.get_storage_profile(storage_profile)
            vapp_storage_profile = E.StorageProfile(
                href=sp.get('href'),
                id=sp.get('href').split('/')[-1],
                type=sp.get('type'),
                name=sp.get('name'))
            sourced_item.append(vapp_storage_profile)

        # Cook the entire vApp Template instantiation element
        deploy_param = 'true' if deploy else 'false'
        power_on_param = 'true' if power_on else 'false'
        all_eulas_accepted = 'true' if accept_all_eulas else 'false'

        vapp_template_params = E.InstantiateVAppTemplateParams(
            name=name, deploy=deploy_param, powerOn=power_on_param)

        if vapp_instantiation_param is not None:
            vapp_template_params.append(vapp_instantiation_param)

        vapp_template_params.append(
            E.Source(href=catalog_item.Entity.get('href')))

        vapp_template_params.append(sourced_item)

        vapp_template_params.append(E.AllEULAsAccepted(all_eulas_accepted))

        # TODO(use post_linked_resource?)
        return self.client.post_resource(
            self.href + '/action/instantiateVAppTemplate',
            vapp_template_params,
            EntityType.INSTANTIATE_VAPP_TEMPLATE_PARAMS.value)

    def list_resources(self, entity_type=None):
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)
        result = []
        if hasattr(self.resource, 'ResourceEntities') and \
           hasattr(self.resource.ResourceEntities, 'ResourceEntity'):
            for vapp in self.resource.ResourceEntities.ResourceEntity:
                if entity_type is None or \
                   entity_type.value == vapp.get('type'):
                    result.append({'name': vapp.get('name')})
        return result

    def add_disk(self,
                 name,
                 size,
                 bus_type=None,
                 bus_sub_type=None,
                 description=None,
                 storage_profile_name=None):
        """
        Request the creation of an indendent disk.
        :param name: (str): The name of the new disk.
        :param size: (int): The size of the new disk in bytes.
        :param bus_type: (str): The bus type of the new disk.
        :param bus_subtype: (str): The bus subtype  of the new disk.
        :param description: (str): A description of the new disk.
        :param storage_profile_name: (str): The name of an existing storage profile to be used by the new disk.
        :return:  A :class:`lxml.objectify.StringElement` object describing the asynchronous Task creating the disk.
        """  # NOQA
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        disk_params = E.DiskCreateParams(E.Disk(name=name, size=str(size)))

        if description is not None:
            disk_params.Disk.append(E.Description(description))

        if bus_type is not None and bus_sub_type is not None:
            disk_params.Disk.attrib['busType'] = bus_type
            disk_params.Disk.attrib['busSubType'] = bus_sub_type

        if storage_profile_name is not None:
            storage_profile = self.get_storage_profile(storage_profile_name)
            disk_params.Disk.append(storage_profile)

        return self.client.post_linked_resource(
            self.resource, RelationType.ADD,
            EntityType.DISK_CREATE_PARMS.value, disk_params)

    def update_disk(self,
                    name,
                    size,
                    new_name=None,
                    description=None,
                    storage_profile_name=None,
                    iops=None,
                    disk_id=None):
        """
        Update an existing independent disk.
        :param name: (str): The existing name of the disk.
        :param size: (int): The size of the new disk in bytes.
        :param new_name: (str): The new name for the disk.
        :param iops: (str): The new iops for the disk.
        :param storage_profile_name: (str): The storage profile that the disk belongs to.
        :param description: (str): A description of the new disk.
        :param disk_id: (str): The disk_id of the existing disk.
        :return:  A :class:`lxml.objectify.StringElement` object describing the asynchronous Task creating the disk.
        """  # NOQA
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        if iops is None:
            disk_params = E.Disk(name=name, size=str(size))
        else:
            disk_params = E.Disk(name=name, size=str(size), iops=iops)

        if description is not None:
            disk_params.append(E.Description(description))

        if disk_id is not None:
            disk = self.get_disk(None, disk_id)
        else:
            disk = self.get_disk(name)

        if storage_profile_name is not None:
            storage_profile = self.get_storage_profile(storage_profile_name)
            sp = etree.XML(etree.tostring(storage_profile, pretty_print=True))
            sp_href = sp.attrib['href']
            disk_params.append(
                E.StorageProfile(href=sp_href, name=storage_profile_name))
        if disk is None:
            raise Exception('Could not locate Disk %s for update. ' % disk_id)

        return self.client.put_linked_resource(
            disk, RelationType.EDIT, EntityType.DISK.value, disk_params)

    def delete_disk(self, name, disk_id=None):
        """
        Delete an existing independent disk.
        :param name: (str): The name of the Disk to delete.
        :param disk_id: (str): The id of the disk to delete.
        :param description: (str): The id of the existing disk.
        :return:  A :class:`lxml.objectify.StringElement` object describing the asynchronous Task creating the disk.
        """  # NOQA
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        if disk_id is not None:
            disk = self.get_disk(None, disk_id)
        else:
            disk = self.get_disk(name)

        return self.client.delete_linked_resource(disk, RelationType.REMOVE,
                                                  None)

    def get_disks(self):
        """
        Request a list of independent disks defined in a vdc.
        :return: An array of :class:`lxml.objectify.StringElement` objects describing the existing Disks.
        """  # NOQA

        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        disks = []
        if hasattr(self.resource, 'ResourceEntities') and \
           hasattr(self.resource.ResourceEntities, 'ResourceEntity'):
            for resourceEntity in \
                    self.resource.ResourceEntities.ResourceEntity:

                if resourceEntity.get('type') == \
                   EntityType.DISK.value:
                    disk = self.client.get_resource(resourceEntity.get('href'))
                    attached_vms = self.client.get_linked_resource(
                        disk, RelationType.DOWN, EntityType.VMS.value)
                    disk['attached_vms'] = attached_vms
                    disks.append(disk)
        return disks

    def get_disk(self, name, disk_id=None):
        """
        Return information for an independent disk.
        :param name: (str): The name of the disk.
        :param disk_id: (str): The id of the disk.
        :return: Disk
        """  # NOQA

        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        disks = self.get_disks()

        result = None
        if disk_id is not None:
            if not disk_id.startswith('urn:vcloud:disk:'):
                disk_id = 'urn:vcloud:disk:' + disk_id
            for disk in disks:
                if disk.get('id') == disk_id:
                    result = disk
                    # disk-id's are unique so it's ok to break the loop
                    # and stop looking further.
                    break
        elif name is not None:
            for disk in disks:
                if disk.get('name') == name:
                    if result is None:
                        result = disk
                    else:
                        raise Exception('Found multiple disks with name %s'
                                        ', please specify disk id along '
                                        'with disk name. ' % disk.get('name'))
        if result is None:
            raise Exception('No disk found with the given name/id.')
        else:
            return result

    def change_disk_owner(self, name, user_href, disk_id=None):
        """
        Change the ownership of an independent disk to a given user.
        :param name: Name of the independent disk.
        :param user_href: Href of the new Owner or User.
        :param disk_id: Disk Id (Required if there are multiple disks with same name).
        :return: None
        """ # NOQA
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        if disk_id is not None:
            disk = self.get_disk(None, disk_id)
        else:
            disk = self.get_disk(name)
        new_owner = disk.Owner
        new_owner.User.set('href', user_href)
        etree.cleanup_namespaces(new_owner)
        return self.client.put_resource(
            disk.get('href') + '/owner/', new_owner, EntityType.OWNER.value)

    def get_storage_profiles(self):
        """
        Request a list of the Storage Profiles defined in a Virtual Data Center.
        :return: An array of :class:`lxml.objectify.StringElement` objects describing the existing Storage Profiles.
        """  # NOQA
        profile_list = []
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        if hasattr(self.resource, 'VdcStorageProfiles') and \
           hasattr(self.resource.VdcStorageProfiles, 'VdcStorageProfile'):
            for profile in self.resource.VdcStorageProfiles.VdcStorageProfile:
                profile_list.append(profile)
                return profile_list
        return None

    def get_storage_profile(self, profile_name):
        """
        Request a specific Storage Profile within a Virtual Data Center.
        :param profile_name: (str): The name of the requested storage profile.
        :return: (VdcStorageProfileType)  A :class:`lxml.objectify.StringElement` object describing the requested storage profile.
        """  # NOQA
        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        if hasattr(self.resource, 'VdcStorageProfiles') and \
           hasattr(self.resource.VdcStorageProfiles, 'VdcStorageProfile'):
            for profile in self.resource.VdcStorageProfiles.VdcStorageProfile:
                if profile.get('name') == profile_name:
                    return profile

        raise Exception(
            'Storage Profile named \'%s\' not found' % profile_name)

    def enable_vdc(self, enable=True):
        """
        Enable current VDC

        :param is_enabled: (bool): enable/disable the vdc
        :return: (OrgVdcType) updated vdc object.
        """  # NOQA

        resource_admin = self.client.get_resource(self.href_admin)
        link = RelationType.ENABLE if enable else RelationType.DISABLE
        return self.client.post_linked_resource(resource_admin, link, None,
                                                None)

    def delete_vdc(self):
        """
        Delete the current Organization vDC
        :param vdc_name: The name of the org vdc to delete
        :return:
        """  # NOQA

        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        return self.client.delete_linked_resource(self.resource,
                                                  RelationType.REMOVE, None)

    def get_access_control_settings(self):
        """Get the access control settings of the vdc.

        :return: (dict): Access control settings of the vdc.
        """
        vdc_resource = self.get_resource()
        access_control_settings = self.client.get_linked_resource(
            vdc_resource, RelationType.DOWN,
            EntityType.CONTROL_ACCESS_PARAMS.value)
        return access_control_settings_to_dict(access_control_settings)

    def create_vapp(self,
                    name,
                    description=None,
                    network=None,
                    fence_mode='bridged',
                    accept_all_eulas=None):
        """Create a new vApp in this VDC

        :param name: (str) Name of the new vApp
        :param description: (str) Description of the new vApp
        :param network: (str) Name of the OrgVDC network to connect the vApp to
        :param fence_mode: (str): Network fence mode.
            Possible values are `bridged` and `natRouted`
        :param accept_all_eulas: (bool): True confirms acceptance of all EULAs
            in a vApp template.
        :return:  A :class:`lxml.objectify.StringElement` object representing a
            sparsely populated vApp element in the target VDC.
        """

        if self.resource is None:
            self.resource = self.client.get_resource(self.href)

        network_href = network_name = None
        if network is not None:
            if hasattr(self.resource, 'AvailableNetworks') and \
               hasattr(self.resource.AvailableNetworks, 'Network'):
                for n in self.resource.AvailableNetworks.Network:
                    if network == n.get('name'):
                        network_href = n.get('href')
                        network_name = n.get('name')
                        break
            if network_href is None:
                raise Exception(
                    'Network \'%s\' not found in the Virtual Datacenter.' %
                    network)

        vapp_instantiation_param = None
        if network_name is not None:
            network_configuration = E.Configuration(
                E.ParentNetwork(href=network_href), E.FenceMode(fence_mode))

            vapp_instantiation_param = E.InstantiationParams(
                E.NetworkConfigSection(
                    E_OVF.Info('Configuration for logical networks'),
                    E.NetworkConfig(
                        network_configuration, networkName=network_name)))

        params = E.ComposeVAppParams(name=name)
        if description is not None:
            params.append(E.Description(description))
        if vapp_instantiation_param is not None:
            params.append(vapp_instantiation_param)
        if accept_all_eulas is not None:
            params.append(E.AllEULAsAccepted(accept_all_eulas))

        return self.client.post_linked_resource(
            self.resource, RelationType.ADD,
            EntityType.COMPOSE_VAPP_PARAMS.value, params)
