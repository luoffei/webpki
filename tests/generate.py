"""
Generates test cases that aim to validate name constraints, name validation,
and other parts of webpki.

Run this script from tests/.  It edits the bottom part of
tests/name_constraints.rs and drops files into tests/name_constraints.
"""


from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import (rsa, ec, ed25519, padding)
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import (NameOID, ExtendedKeyUsageOID)
import ipaddress
import datetime

ISSUER_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)
ISSUER_PUBLIC_KEY = ISSUER_PRIVATE_KEY.public_key()

NOT_BEFORE = datetime.datetime.fromtimestamp(0x1fedf00d - 30)
NOT_AFTER = datetime.datetime.fromtimestamp(0x1fedf00d + 30)


def trim_top(file_name):
    """
    Reads `file_name`, then writes lines up to a particular comment (the "top"
    of the file) back to it and returns the file object for further writing.
    """

    with open(file_name, 'r') as f:
        top = f.readlines()
    top = top[:top.index('// DO NOT EDIT BELOW: generated by tests/generate.py\n')+1]
    output = open(file_name, 'w')
    for l in top:
        output.write(l)
    return output


def name_constraints():
    def test(test_name,
            expected_error=None,
            subject_common_name=None,
            extra_subject_names=[],
            valid_names=[],
            invalid_names=[],
            sans=None,
            permitted_subtrees=None,
            excluded_subtrees=None):
        """
        Generate a test case, writing a rust '#[test]' function into
        name_constraints.rs, and writing supporting files into the current
        directory.

        - `test_name`: name of the test, must be a rust identifier.
        - `expected_error`: item in `webpki::Error` enum, expected error from
          webpki `verify_is_valid_tls_server_cert` function.  Leave absent to
          expect success.
        - `subject_common_name`: optional string to put in end-entity certificate
          subject common name.
        - `extra_subject_names`: optional sequence of `x509.NameAttributes` to add
          to end-entity certificate subject.
        - `valid_names`: optional sequence of valid names that the end-entity
          certificate is expected to pass `verify_is_valid_for_subject_name` for.
        - `invalid_names`: optional sequence of invalid names that the end-entity
          certificate is expected to fail `verify_is_valid_for_subject_name` with
          `CertNotValidForName`.
        - `sans`: optional sequence of `x509.GeneralName`s that are the contents of
          the subjectAltNames extension.  If empty or not provided the end-entity
          certificate does not have a subjectAltName extension.
        - `permitted_subtrees`: optional sequence of `x509.GeneralName`s that are
          the `permittedSubtrees` contents of the `nameConstraints` extension.
          If this and `excluded_subtrees` are empty/absent then the end-entity
          certificate does not have a `nameConstraints` extension.
        - `excluded_subtrees`: optional sequence of `x509.GeneralName`s that are
          the `excludedSubtrees` contents of the `nameConstraints` extension.
          If this and `permitted_subtrees` are both empty/absent then the
          end-entity  certificate does not have a `nameConstraints` extension.
          """

        # keys must be valid but are otherwise unimportant for these tests
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key = private_key.public_key()

        issuer_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u'issuer.example.com'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, test_name),
        ])

        # end-entity
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(x509.Name(
            ([x509.NameAttribute(NameOID.COMMON_NAME, subject_common_name)] if subject_common_name else []) +
            [x509.NameAttribute(NameOID.ORGANIZATION_NAME, test_name) ] +
            extra_subject_names
        ))
        builder = builder.issuer_name(issuer_name)

        builder = builder.not_valid_before(NOT_BEFORE)
        builder = builder.not_valid_after(NOT_AFTER)
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(public_key)
        if sans:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(sans),
                critical=False
            )
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        certificate = builder.sign(
            private_key=ISSUER_PRIVATE_KEY,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        with open('name_constraints/' + test_name + '.ee.der', 'wb') as f:
            f.write(certificate.public_bytes(Encoding.DER))

        # issuer
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(issuer_name)
        builder = builder.issuer_name(issuer_name)
        builder = builder.not_valid_before(NOT_BEFORE)
        builder = builder.not_valid_after(NOT_AFTER)
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(ISSUER_PUBLIC_KEY)
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True,
        )
        if permitted_subtrees or excluded_subtrees:
            builder = builder.add_extension(
                x509.NameConstraints(permitted_subtrees, excluded_subtrees),
                critical=True
            )

        certificate = builder.sign(
            private_key=ISSUER_PRIVATE_KEY,
            algorithm=hashes.SHA256(),
            backend=default_backend()
        )

        with open('name_constraints/' + test_name + '.ca.der', 'wb') as f:
            f.write(certificate.public_bytes(Encoding.DER))

        if expected_error is None:
            expected = 'Ok(())'
        else:
            expected = 'Err(webpki::Error::' + expected_error + ')'

        valid_names = ', '.join('"' + name + '"' for name in valid_names)
        invalid_names = ', '.join('"' + name + '"' for name in invalid_names)

        print("""
#[test]
#[cfg(feature = "alloc")]
fn %(test_name)s() {
    let ee = include_bytes!("name_constraints/%(test_name)s.ee.der");
    let ca = include_bytes!("name_constraints/%(test_name)s.ca.der");
    assert_eq!(
        check_cert(ee, ca, &[%(valid_names)s], &[%(invalid_names)s]),
        %(expected)s
    );
}""" % locals(), file=output)

    output = trim_top('name_constraints.rs')

    test(
        'no_name_constraints',
        subject_common_name='subject.example.com',
        valid_names=['dns.example.com'],
        invalid_names=['subject.example.com'],
        sans=[x509.DNSName('dns.example.com')])

    test(
        'additional_dns_labels',
        subject_common_name='subject.example.com',
        valid_names=['host1.example.com', 'host2.example.com'],
        invalid_names=['subject.example.com'],
        sans=[x509.DNSName('host1.example.com'), x509.DNSName('host2.example.com')],
        permitted_subtrees=[x509.DNSName('.example.com')])


    test(
        'disallow_subject_common_name',
        expected_error='UnknownIssuer',
        subject_common_name='disallowed.example.com',
        excluded_subtrees=[x509.DNSName('disallowed.example.com')])
    test(
        'disallow_dns_san',
        expected_error='UnknownIssuer',
        sans=[x509.DNSName('disallowed.example.com')],
        excluded_subtrees=[x509.DNSName('disallowed.example.com')])

    test(
        'allow_subject_common_name',
        subject_common_name='allowed.example.com',
        invalid_names=['allowed.example.com'],
        permitted_subtrees=[x509.DNSName('allowed.example.com')])
    test(
        'allow_dns_san',
        valid_names=['allowed.example.com'],
        sans=[x509.DNSName('allowed.example.com')],
        permitted_subtrees=[x509.DNSName('allowed.example.com')])
    test(
        'allow_dns_san_and_subject_common_name',
        valid_names=['allowed-san.example.com'],
        invalid_names=['allowed-cn.example.com'],
        sans=[x509.DNSName('allowed-san.example.com')],
        subject_common_name='allowed-cn.example.com',
        permitted_subtrees=[x509.DNSName('allowed-san.example.com'), x509.DNSName('allowed-cn.example.com')])
    test(
        'allow_dns_san_and_disallow_subject_common_name',
        expected_error='UnknownIssuer',
        sans=[x509.DNSName('allowed-san.example.com')],
        subject_common_name='disallowed-cn.example.com',
        permitted_subtrees=[x509.DNSName('allowed-san.example.com')],
        excluded_subtrees=[x509.DNSName('disallowed-cn.example.com')])
    test(
        'disallow_dns_san_and_allow_subject_common_name',
        expected_error='UnknownIssuer',
        sans=[x509.DNSName('allowed-san.example.com'), x509.DNSName('disallowed-san.example.com')],
        subject_common_name='allowed-cn.example.com',
        permitted_subtrees=[x509.DNSName('allowed-san.example.com'), x509.DNSName('allowed-cn.example.com')],
        excluded_subtrees=[x509.DNSName('disallowed-san.example.com')])

    # XXX: ideally this test case would be a negative one, because the name constraints
    # should apply to the subject name.
    # however, because we don't look at email addresses in subjects, it is accepted.
    test(
        'we_incorrectly_ignore_name_constraints_on_name_in_subject',
        extra_subject_names=[x509.NameAttribute(NameOID.EMAIL_ADDRESS, 'joe@notexample.com')],
        permitted_subtrees=[x509.RFC822Name('example.com')])

    # this does work, however, because we process all SANs
    test(
        'reject_constraints_on_unimplemented_names',
        expected_error='UnknownIssuer',
        sans=[x509.RFC822Name('joe@example.com')],
        permitted_subtrees=[x509.RFC822Name('example.com')])

    # RFC5280 4.2.1.10:
    #   "If no name of the type is in the certificate,
    #    the certificate is acceptable."
    test(
        'we_ignore_constraints_on_names_that_do_not_appear_in_cert',
        sans=[x509.DNSName('notexample.com')],
        valid_names=['notexample.com'],
        invalid_names=['example.com'],
        permitted_subtrees=[x509.RFC822Name('example.com')])

    test(
        'wildcard_san_accepted_if_in_subtree',
        sans=[x509.DNSName('*.example.com')],
        valid_names=['bob.example.com', 'jane.example.com'],
        invalid_names=['example.com', 'uh.oh.example.com'],
        permitted_subtrees=[x509.DNSName('example.com')])

    test(
        'wildcard_san_rejected_if_in_excluded_subtree',
        expected_error='UnknownIssuer',
        sans=[x509.DNSName('*.example.com')],
        excluded_subtrees=[x509.DNSName('example.com')])

    test(
        'ip4_address_san_rejected_if_in_excluded_subtree',
        expected_error='UnknownIssuer',
        sans=[x509.IPAddress(ipaddress.ip_address('12.34.56.78'))],
        excluded_subtrees=[x509.IPAddress(ipaddress.ip_network('12.34.56.0/24'))])

    test(
        'ip4_address_san_allowed_if_outside_excluded_subtree',
        valid_names=['12.34.56.78'],
        sans=[x509.IPAddress(ipaddress.ip_address('12.34.56.78'))],
        excluded_subtrees=[x509.IPAddress(ipaddress.ip_network('12.34.56.252/30'))])

    sparse_net_addr = ipaddress.ip_network('12.34.56.78/24', strict=False)
    sparse_net_addr.netmask = ipaddress.ip_address('255.255.255.1')
    test(
        'ip4_address_san_rejected_if_excluded_is_sparse_cidr_mask',
        expected_error='UnknownIssuer',
        sans=[
            # inside excluded network, if netmask is allowed to be sparse
            x509.IPAddress(ipaddress.ip_address('12.34.56.79')),
        ],
        excluded_subtrees=[x509.IPAddress(sparse_net_addr)])


    test(
        'ip4_address_san_allowed',
        valid_names=['12.34.56.78'],
        invalid_names=['12.34.56.77', '12.34.56.79', '0000:0000:0000:0000:0000:ffff:0c22:384e'],
        sans=[x509.IPAddress(ipaddress.ip_address('12.34.56.78'))],
        permitted_subtrees=[x509.IPAddress(ipaddress.ip_network('12.34.56.0/24'))])

    test(
        'ip6_address_san_rejected_if_in_excluded_subtree',
        expected_error='UnknownIssuer',
        sans=[x509.IPAddress(ipaddress.ip_address('2001:db8::1'))],
        excluded_subtrees=[x509.IPAddress(ipaddress.ip_network('2001:db8::/48'))])

    test(
        'ip6_address_san_allowed_if_outside_excluded_subtree',
        valid_names=['2001:0db9:0000:0000:0000:0000:0000:0001'],
        sans=[x509.IPAddress(ipaddress.ip_address('2001:db9::1'))],
        excluded_subtrees=[x509.IPAddress(ipaddress.ip_network('2001:db8::/48'))])

    test(
        'ip6_address_san_allowed',
        valid_names=['2001:0db9:0000:0000:0000:0000:0000:0001'],
        invalid_names=['12.34.56.78'],
        sans=[x509.IPAddress(ipaddress.ip_address('2001:db9::1'))],
        permitted_subtrees=[x509.IPAddress(ipaddress.ip_network('2001:db9::/48'))])

    test(
        'ip46_mixed_address_san_allowed',
        valid_names=['12.34.56.78', '2001:0db9:0000:0000:0000:0000:0000:0001'],
        invalid_names=['12.34.56.77', '12.34.56.79', '0000:0000:0000:0000:0000:ffff:0c22:384e'],
        sans=[
            x509.IPAddress(ipaddress.ip_address('12.34.56.78')),
            x509.IPAddress(ipaddress.ip_address('2001:db9::1')),
        ],
        permitted_subtrees=[
            x509.IPAddress(ipaddress.ip_network('12.34.56.0/24')),
            x509.IPAddress(ipaddress.ip_network('2001:db9::/48'))
        ])

    test(
        'permit_directory_name_not_implemented',
        expected_error='UnknownIssuer',
        permitted_subtrees=[
            x509.DirectoryName(x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, u'CN')]))
        ])

    test(
        'exclude_directory_name_not_implemented',
        expected_error='UnknownIssuer',
        excluded_subtrees=[
            x509.DirectoryName(x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, u'CN')]))
        ])

    output.close()


def signatures():
    rsa_pub_exponent = 0x10001
    backend = default_backend()
    all_key_types = {
        'ed25519': ed25519.Ed25519PrivateKey.generate(),
        'ecdsa_p256': ec.generate_private_key(ec.SECP256R1(), backend),
        'ecdsa_p384': ec.generate_private_key(ec.SECP384R1(), backend),
        'ecdsa_p521_not_supported': ec.generate_private_key(ec.SECP521R1(), backend),
        'rsa_1024_not_supported': rsa.generate_private_key(rsa_pub_exponent, 1024, backend),
        'rsa_2048': rsa.generate_private_key(rsa_pub_exponent, 2048, backend),
        'rsa_3072': rsa.generate_private_key(rsa_pub_exponent, 3072, backend),
        'rsa_4096': rsa.generate_private_key(rsa_pub_exponent, 4096, backend),
    }

    rsa_types = [
        'RSA_PKCS1_2048_8192_SHA256',
        'RSA_PKCS1_2048_8192_SHA384',
        'RSA_PKCS1_2048_8192_SHA512',
        'RSA_PSS_2048_8192_SHA256_LEGACY_KEY',
        'RSA_PSS_2048_8192_SHA384_LEGACY_KEY',
        'RSA_PSS_2048_8192_SHA512_LEGACY_KEY'
    ]

    webpki_algs = {
        'ed25519': ['ED25519'],
        'ecdsa_p256': ['ECDSA_P256_SHA384', 'ECDSA_P256_SHA256'],
        'ecdsa_p384': ['ECDSA_P384_SHA384', 'ECDSA_P384_SHA256'],
        'rsa_2048': rsa_types,
        'rsa_3072': rsa_types + ['RSA_PKCS1_3072_8192_SHA384'],
        'rsa_4096': rsa_types + ['RSA_PKCS1_3072_8192_SHA384'],
    }

    pss_sha256 = padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=32)
    pss_sha384 = padding.PSS(
        mgf=padding.MGF1(hashes.SHA384()),
        salt_length=48)
    pss_sha512 = padding.PSS(
        mgf=padding.MGF1(hashes.SHA512()),
        salt_length=64)

    how_to_sign = {
        'ED25519': lambda key, message: key.sign(message),
        'ECDSA_P256_SHA256': lambda key, message: key.sign(message, ec.ECDSA(hashes.SHA256())),
        'ECDSA_P256_SHA384': lambda key, message: key.sign(message, ec.ECDSA(hashes.SHA384())),
        'ECDSA_P384_SHA256': lambda key, message: key.sign(message, ec.ECDSA(hashes.SHA256())),
        'ECDSA_P384_SHA384': lambda key, message: key.sign(message, ec.ECDSA(hashes.SHA384())),
        'RSA_PKCS1_2048_8192_SHA256': lambda key, message: key.sign(message, padding.PKCS1v15(), hashes.SHA256()),
        'RSA_PKCS1_2048_8192_SHA384': lambda key, message: key.sign(message, padding.PKCS1v15(), hashes.SHA384()),
        'RSA_PKCS1_2048_8192_SHA512': lambda key, message: key.sign(message, padding.PKCS1v15(), hashes.SHA512()),
        'RSA_PKCS1_3072_8192_SHA384': lambda key, message: key.sign(message, padding.PKCS1v15(), hashes.SHA384()),
        'RSA_PSS_2048_8192_SHA256_LEGACY_KEY': lambda key, message: key.sign(message, pss_sha256, hashes.SHA256()),
        'RSA_PSS_2048_8192_SHA384_LEGACY_KEY': lambda key, message: key.sign(message, pss_sha384, hashes.SHA384()),
        'RSA_PSS_2048_8192_SHA512_LEGACY_KEY': lambda key, message: key.sign(message, pss_sha512, hashes.SHA512()),
    }

    for name, private_key in all_key_types.items():
        # end-entity
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(x509.Name(
            [x509.NameAttribute(NameOID.ORGANIZATION_NAME, name + ' test') ]
        ))
        builder = builder.issuer_name(x509.Name(
            [x509.NameAttribute(NameOID.ORGANIZATION_NAME, name + ' issuer') ]
        ))

        builder = builder.not_valid_before(NOT_BEFORE)
        builder = builder.not_valid_after(NOT_AFTER)
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(private_key.public_key())
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        certificate = builder.sign(
            private_key=ISSUER_PRIVATE_KEY,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        with open('signatures/' + name + '.ee.der', 'wb') as f:
            f.write(certificate.public_bytes(Encoding.DER))

    def _test(test_name, cert, algorithm, signature, expected):
        test_name = test_name.lower()

        with open('signatures/' + test_name + '.sig.bin', 'wb') as f:
            f.write(signature)

        print("""
#[test]
#[cfg(feature = "alloc")]
fn %(test_name)s() {
    let ee = include_bytes!("signatures/%(cert)s.ee.der");
    let message = include_bytes!("signatures/message.bin");
    let signature = include_bytes!("signatures/%(test_name)s.sig.bin");
    assert_eq!(
        check_sig(ee, &webpki::%(algorithm)s, message, signature),
        %(expected)s
    );
}""" % locals(), file=output)

    message = b'hello world!'

    with open('signatures/message.bin', 'wb') as f:
        f.write(message)

    def good_signature(test_name, cert, algorithm, signer):
        signature = signer(all_key_types[cert], message)
        _test(test_name, cert, algorithm, signature, expected='Ok(())')

    def good_signature_but_rejected(test_name, cert, algorithm, signer):
        signature = signer(all_key_types[cert], message)
        _test(test_name, cert, algorithm, signature, expected='Err(webpki::Error::InvalidSignatureForPublicKey)')

    def bad_signature(test_name, cert, algorithm, signer):
        signature = signer(all_key_types[cert], message + b'?')
        _test(test_name, cert, algorithm, signature, expected='Err(webpki::Error::InvalidSignatureForPublicKey)')

    def bad_algorithms_for_key(test_name, cert, unusable_algs):
        test_name = test_name.lower()
        unusable_algs = ', '.join('&webpki::' + alg for alg in sorted(unusable_algs))
        print("""
#[test]
#[cfg(feature = "alloc")]
fn %(test_name)s() {
    let ee = include_bytes!("signatures/%(cert)s.ee.der");
    for algorithm in &[ %(unusable_algs)s ] {
        assert_eq!(
            check_sig(ee, algorithm, b"", b""),
            Err(webpki::Error::UnsupportedSignatureAlgorithmForPublicKey)
        );
    }
}""" % locals(), file=output)

    output = trim_top('signatures.rs')

    # compute all webpki algorithms covered by these tests
    all_webpki_algs = set([item for algs in webpki_algs.values() for item in algs])

    for type, algs in webpki_algs.items():
        for alg in algs:
            signer = how_to_sign[alg]
            good_signature(
                type + '_key_and_' + alg + '_good_signature',
                cert=type,
                algorithm=alg,
                signer=signer)
            bad_signature(
                type + '_key_and_' + alg + '_detects_bad_signature',
                cert=type,
                algorithm=alg,
                signer=signer)

        unusable_algs = set(all_webpki_algs)
        for alg in algs:
            unusable_algs.remove(alg)

        # special case: tested separately below
        if type == 'rsa_2048':
            unusable_algs.remove('RSA_PKCS1_3072_8192_SHA384')

        bad_algorithms_for_key(
            type + '_key_rejected_by_other_algorithms',
            cert=type,
            unusable_algs=unusable_algs)

    good_signature_but_rejected(
        'rsa_2048_key_rejected_by_RSA_PKCS1_3072_8192_SHA384',
        cert='rsa_2048',
        algorithm='RSA_PKCS1_3072_8192_SHA384',
        signer=signer)

    output.close()


def client_auth():
    def test(test_name,
            ekus,
            expected_error=None):
        # keys must be valid but are otherwise unimportant for these tests
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key = private_key.public_key()

        issuer_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u'issuer.example.com'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, test_name),
        ])

        # end-entity
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(x509.Name(
            [x509.NameAttribute(NameOID.ORGANIZATION_NAME, test_name) ]
        ))
        builder = builder.issuer_name(issuer_name)

        builder = builder.not_valid_before(NOT_BEFORE)
        builder = builder.not_valid_after(NOT_AFTER)
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(public_key)
        if ekus:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(ekus),
                critical=False
            )
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        certificate = builder.sign(
            private_key=ISSUER_PRIVATE_KEY,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        with open('client_auth/' + test_name + '.ee.der', 'wb') as f:
            f.write(certificate.public_bytes(Encoding.DER))

        # issuer
        builder = x509.CertificateBuilder()
        builder = builder.subject_name(issuer_name)
        builder = builder.issuer_name(issuer_name)
        builder = builder.not_valid_before(NOT_BEFORE)
        builder = builder.not_valid_after(NOT_AFTER)
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(ISSUER_PUBLIC_KEY)
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True,
        )

        certificate = builder.sign(
            private_key=ISSUER_PRIVATE_KEY,
            algorithm=hashes.SHA256(),
            backend=default_backend()
        )

        with open('client_auth/' + test_name + '.ca.der', 'wb') as f:
            f.write(certificate.public_bytes(Encoding.DER))

        if expected_error is None:
            expected = 'Ok(())'
        else:
            expected = 'Err(webpki::Error::' + expected_error + ')'

        print("""
#[test]
#[cfg(feature = "alloc")]
fn %(test_name)s() {
    let ee = include_bytes!("client_auth/%(test_name)s.ee.der");
    let ca = include_bytes!("client_auth/%(test_name)s.ca.der");
    assert_eq!(
        check_cert(ee, ca),
        %(expected)s
    );
}""" % locals(), file=output)

    output = trim_top('client_auth.rs')

    test('cert_with_no_eku_accepted_for_client_auth',
        ekus=None)
    test('cert_with_clientauth_eku_accepted_for_client_auth',
        ekus=[ExtendedKeyUsageOID.CLIENT_AUTH])
    test('cert_with_both_ekus_accepted_for_client_auth',
        ekus=[
            ExtendedKeyUsageOID.CLIENT_AUTH,
            ExtendedKeyUsageOID.SERVER_AUTH
        ])
    test('cert_with_serverauth_eku_rejected_for_client_auth',
        ekus=[ExtendedKeyUsageOID.SERVER_AUTH],
        expected_error='RequiredEkuNotFound')

    output.close()


name_constraints()
signatures()
client_auth()
