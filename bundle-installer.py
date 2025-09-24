#!/usr/local/bin/python -u

import argparse
import logging
import subprocess
import os
import time

# please make sure JDK 17 has been installed
java = ['java']

log = logging.getLogger(__name__)
parser = argparse.ArgumentParser(
    description='Automation script to install an aab for a connected Android device')

parser.add_argument('-b', '--bundle', dest='bundle',
                    help='bundle file full path', required=True)
parser.add_argument('-ksf', '--keystore-file', dest='keystore',
                    help='keystore file full path', required=True)
parser.add_argument('-ksp', '--keystore-pass', dest='keystore_pass',
                    help='keystore pass', required=True)
parser.add_argument('-alias', '--keystore-alias', dest='alias',
                    help='keystore alias', required=True)
parser.add_argument('-kpass', '--key-pass', dest='key_pass',
                    help='key pass', required=True)

args_in = parser.parse_args()


def run_jar(args):
    args = java + ['-jar', './jar/bundletool-all-1.18.1.jar'] + args

    # print('exec cmd : %s' % args)
    out = None

    p = subprocess.Popen([str(arg) for arg in args])
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr


def automate():
    try:
        apks_file = "./cache/%s.apks" % str(time.time())
        if os.path.exists(apks_file):
            os.remove(apks_file)

        print("Building apks for bundle : %s" % args_in.bundle)
        (code, out, err) = run_jar(
            ['build-apks', "--bundle=%s" % args_in.bundle, "--output=%s" % apks_file, "--ks=%s" % args_in.keystore,
             "--ks-pass=pass:%s" % args_in.keystore_pass, "--ks-key-alias=%s" % args_in.alias,
             "--key-pass=pass:%s" % args_in.key_pass])
        print("result code: %d" % code)
        print("apks file generated : %s" % apks_file)

        if code == 0:
            print("Installing apks for connected device")
            run_jar(
                ['install-apks', "--apks=%s" % apks_file]
            )

    except Exception as e:
        print(e)


if __name__ == "__main__":
    automate()
