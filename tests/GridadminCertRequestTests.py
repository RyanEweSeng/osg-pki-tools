"""Test osg-gridadmin-cert-request script"""

import re
import unittest
from M2Crypto import X509, RSA

from PKIClientTestCase import OIM, DOMAIN, test_env_setup, test_env_teardown

class GridadminCertRequestTests(unittest.TestCase):

    __num_multihost_requests = 2

    def setUp(self):
        """Run each test in its own dir"""
        test_env_setup()

    def tearDown(self):
        """Remove personal test dir"""
        test_env_teardown()

    def write_hostsfile(self, hosts):
        """Write the hosts input file"""
        hosts_filename = "hosts.txt"
        hosts_contents = str()
        for sans in hosts:
            hosts_contents += " ".join(sans) + "\n"
        f = open(hosts_filename, 'w')
        f.write(hosts_contents)
        f.flush()
        f.close()
        return hosts_filename

    def verify_num_certs(self, found_certs, expected_certs, msg):
        """Verify expected number of certs. If not, throw an AssertionError with details and msg"""
        num_found_certs = len(found_certs)
        num_expected_certs = len(expected_certs)
        self.assertEqual(num_found_certs, num_expected_certs,
                         'Expected %s cert(s), received %s\n%s' % (num_found_certs, num_expected_certs, msg))

    def verify_sans(self, certs, hosts, msg):
        """Verify that the we have the correct number of certs and expected SAN contents for each cert.
        If not, throw an AssertionError with details and msg"""
        self.verify_num_certs(certs, hosts, msg)
        for cert, expected_names in zip(certs, hosts):
            # Verify list of SANs are as expected
            san_contents = cert.get_ext('subjectAltName').get_value()
            found_names = set(match.group(1) for match in re.finditer(r'DNS:([\w\-\.]+)', san_contents))
            self.assertEqual(found_names, set(expected_names),
                             "Did not find expected SAN contents %s:\n%s\n%s" %
                             (expected_names, cert.as_text(), msg))

    def test_help(self):
        """Test running with -h to get help"""
        rc, stdout, _, msg = OIM().gridadmin_request('--help')
        self.assertEqual(rc, 0, "Bad return code when requesting help\n%s" % msg)
        self.assert_(re.search(r'[Uu]sage:', stdout), msg)

    def test_no_args(self):
        """Ensure failure when no args are provided"""
        rc, _, stderr, msg = OIM().gridadmin_request()
        self.assertNotEqual(rc, 0, 'Unexpected success with no args')
        self.assert_(re.search(r'[Uu]sage:', stderr), msg)
        print stdout

    def test_cert_request(self):
        """Test making a request for a single host"""
        rc, _, _, msg = OIM().gridadmin_request('--hostname', 'test.' + DOMAIN)
        self.assertEqual(rc, 0, "Failed to request certificate\n%s" % msg)

    def test_alt_name_request(self):
        """Test making a request for a single host with an alternative hostname"""
        hostname = 'test.' + DOMAIN
        san = 'test-san.' + DOMAIN
        second_san = 'test-san2.' + DOMAIN
        request = OIM()
        rc, _, _, msg = request.gridadmin_request('--hostname', hostname,
                                                  '--altname', san,
                                                  '--altname', second_san)
        self.assertEqual(rc, 0, "Failed to request certificate\n%s" % msg)
        self.verify_sans(request.certs, [[hostname, san, second_san]], msg)

    def test_rename_old_certs(self):
        """Test repeated requests for the same host to make sure
        we aren't overwriting files.

        https://jira.opensciencegrid.org/browse/OSGPKI-137
        https://jira.opensciencegrid.org/browse/OSGPKI-139
        """
        hostname = 'test.' + DOMAIN
        initial_req = OIM()
        rc, _, _, msg = initial_req.gridadmin_request('--hostname', hostname)
        self.assertEqual(rc, 0, "Failed to request initial certificate\n%s" % msg)

        # Request another cert that will move the previous cert out of the way
        rc, stdout, _, msg = OIM().gridadmin_request('--hostname', hostname)
        self.assertEqual(rc, 0, "Failed to request second certificate\n%s" % msg)

        # Verify that the moved key/cert pair is the same as in the initial request
        try:
            old_cert_path = re.search(r'Renaming existing file to (.*)', stdout).group(1)
            old_key_path = re.search(r'Renaming existing key from.*to (.*)', stdout).group(1)
        except AttributeError:
            self.fail('Failed to move old cert or key\n' + msg)

        old_cert = X509.load_cert(old_cert_path).as_pem()
        self.assertEqual(initial_req.certs[0].as_pem(), old_cert,
                         'Renamed cert is not the same as the initial cert' + msg)
        old_key = RSA.load_key(old_key_path, OIM.simple_pass_callback)
        old_key_pem = old_key.as_pem(cipher=None, callback=OIM.simple_pass_callback)
        initial_key_pem = initial_req.keys[0].as_pem(cipher=None, callback=OIM.simple_pass_callback)
        self.assertEqual(initial_key_pem, old_key_pem,
                         'Renamed cert is not the same as the initial cert' + msg)

    def test_multihost_request(self):
        """Test making a request for multiple host certificates"""
        # Generate a simple hosts list
        hosts = list(["test-%d.%s" % (i, DOMAIN)] for i in xrange(self.__num_multihost_requests))
        hosts_file = self.write_hostsfile(hosts)

        # Request the certs
        request = OIM()
        rc, _, _, msg = request.gridadmin_request("--hostfile", hosts_file)

        self.assertEqual(rc, 0, "Failed to request certificate\n" + msg)
        self.verify_num_certs(request.certs, hosts, msg)

    def test_duplicate_host_request(self):
        """Ignore duplicate hosts"""
        hosts = list(["test-%d.%s" % (i, DOMAIN)] for i in xrange(self.__num_multihost_requests))
        extra_hosts = hosts + [['test-0.%s' % DOMAIN]]
        hosts_file = self.write_hostsfile(extra_hosts)

        # Request the certs
        request = OIM()
        rc, _, _, msg = request.gridadmin_request("--hostfile", hosts_file)

        self.assertEqual(rc, 0, "Failed to request certificate\n" + msg)
        self.verify_sans(request.certs, hosts, msg)

    def test_multihost_sans_request(self):
        """Submit cert request for multiple hosts with SANs for each host"""
        # Generate the hosts list with SANs for each host
        hosts = list()
        for i in xrange(self.__num_multihost_requests):
            hosts.append([name.format(i, DOMAIN) for name in
                          ["test-{0}.{1}", "test-{0}-san.{1}", "test-{0}-san2.{1}"]])
        hosts_file = self.write_hostsfile(hosts)

        # Request the certs
        request = OIM()
        rc, _, _, msg = request.gridadmin_request("--hostfile", hosts_file)

        self.assertEqual(rc, 0, "Failed to request certificate\n%s" % msg)
        self.verify_sans(request.certs, hosts, msg)

    def test_multihost_mixed_request(self):
        """Submit cert request for multiple hosts with SANs for some hosts """
        # Generate the hosts list with every other host having SANs
        hosts = list()
        for i in xrange(self.__num_multihost_requests):
            if i % 2 == 1:
                hosts.append(["test-%d.%s" % (i, DOMAIN)])
            else:
                hosts.append([name.format(i, DOMAIN) for name in
                              ["test-{0}.{1}", "test-{0}-san.{1}", "test-{0}-san2.{1}"]])
        hosts_file = self.write_hostsfile(hosts)

        # Request the certs
        request = OIM()
        rc, _, _, msg = request.gridadmin_request("--hostfile", hosts_file)

        self.assertEqual(rc, 0, "Failed to request certificate\n%s" % msg)
        self.verify_sans(request.certs, hosts, msg)

if __name__ == '__main__':
    unittest.main()
