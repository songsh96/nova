# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Michael Still and Canonical Inc
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import fixtures
import os
from testtools.matchers import Equals
from testtools.matchers import MatchesListwise

from nova import test

from nova import utils
from nova.virt.disk.mount import nbd

ORIG_EXISTS = os.path.exists
ORIG_LISTDIR = os.listdir


def _fake_exists_no_users(path):
    if path.startswith('/sys/block/nbd'):
        if path.endswith('pid'):
            return False
        return True
    return ORIG_EXISTS(path)


def _fake_listdir_nbd_devices(path):
    if path.startswith('/sys/block'):
        return ['nbd0', 'nbd1']
    return ORIG_LISTDIR(path)


def _fake_exists_no_users(path):
    if path.startswith('/sys/block/nbd'):
        if path.endswith('pid'):
            return False
        return True
    return ORIG_EXISTS(path)


def _fake_exists_all_used(path):
    if path.startswith('/sys/block/nbd'):
        return True
    return ORIG_EXISTS(path)


def _fake_detect_nbd_devices_none(self):
    return []


def _fake_detect_nbd_devices(self):
    return ['nbd0', 'nbd1']


def _fake_noop(*args, **kwargs):
    return


class NbdTestCase(test.TestCase):
    def setUp(self):
        super(NbdTestCase, self).setUp()
        self.useFixture(fixtures.MonkeyPatch('os.listdir',
                                             _fake_listdir_nbd_devices))

    def test_nbd_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.detect_nbd_device = _fake_detect_nbd_devices_none
        self.assertEquals(None, n._allocate_nbd())

    def test_nbd_no_free_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_all_used))
        self.assertEquals(None, n._allocate_nbd())

    def test_nbd_not_loaded(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                return False
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # This should fail, as we don't have the module "loaded"
        # TODO(mikal): work out how to force english as the gettext language
        # so that the error check always passes
        self.assertEquals(None, n._allocate_nbd())
        self.assertEquals('nbd unavailable: module not loaded', n.error)

    def test_nbd_allocation(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.detect_nbd_device = _fake_detect_nbd_devices
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Allocate a nbd device
        self.assertEquals('/dev/nbd0', n._allocate_nbd())

    def test_nbd_allocation_one_in_use(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd0/pid':
                    return True
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # Allocate a nbd device, should not be the in use one
        # TODO(mikal): Note that there is a leak here, as the in use nbd device
        # is removed from the list, but not returned so it will never be
        # re-added. I will fix this in a later patch.
        self.assertEquals('/dev/nbd1', n._allocate_nbd())

    def test_get_dev_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.detect_nbd_device = _fake_detect_nbd_devices
        self.assertFalse(n.get_dev())

    def test_get_dev_qemu_fails(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always fails
        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # Error logged, no device consumed
        self.assertFalse(n.get_dev())
        self.assertTrue(n.error.startswith('qemu-nbd error'))

    def test_get_dev_qemu_timeout(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.detect_nbd_device = _fake_detect_nbd_devices
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always passed
        def fake_trycmd(*args, **kwargs):
            return '', ''
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))
        self.useFixture(fixtures.MonkeyPatch('time.sleep', _fake_noop))

        # Error logged, no device consumed
        self.assertFalse(n.get_dev())
        self.assertTrue(n.error.endswith('did not show up'))

    def test_get_dev_works(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.detect_nbd_device = _fake_detect_nbd_devices
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))

        # We need the pid file for the device which is allocated to exist, but
        # only once it is allocated to us
        def fake_exists_one(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd1/pid':
                    return False
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             fake_exists_one))

        # We have a trycmd that always passed
        def fake_trycmd(*args, **kwargs):
            def fake_exists_two(path):
                if path.startswith('/sys/block/nbd'):
                    if path == '/sys/block/nbd0/pid':
                        return True
                    if path.endswith('pid'):
                        return False
                    return True
                return ORIG_EXISTS(path)
            self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                                 fake_exists_two))
            return '', ''
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # No error logged, device consumed
        self.assertTrue(n.get_dev())
        self.assertTrue(n.linked)
        self.assertEquals('', n.error)
        self.assertEquals('/dev/nbd0', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEquals('', n.error)
        self.assertEquals(None, n.device)

    def test_unget_dev_simple(self):
        # This test is just checking we don't get an exception when we unget
        # something we don't have
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.unget_dev()
