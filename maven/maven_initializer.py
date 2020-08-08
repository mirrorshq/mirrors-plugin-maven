#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import os
import re
import sys
import time
import json
import random
import socket
import subprocess


PROGRESS_STAGE_1 = 10
PROGRESS_STAGE_2 = 70
PROGRESS_STAGE_3 = 20


def main():
    sock = MUtil.connect()
    try:
        dataDir = json.loads(sys.argv[1])["storage-file"]["data-directory"]
        rsyncSource = "rsync://mirrors.tuna.tsinghua.edu.cn/maven"
        fileSource = "https://mirrors.tuna.tsinghua.edu.cn/maven"

        # stage1: create directories, get file list, ignore symlinks (file donwloaders can not cope with symlinks)
        print("Start fetching file list.")
        fileList = _makeDirAndGetFileList(rsyncSource, dataDir)
        print("File list fetched, total %d files." % (len(fileList)))
        MUtil.progress_changed(sock, PROGRESS_STAGE_1)

        # stage2: download file list
        i = 1
        total = len(fileList)
        for fn in Util.randomSorted(fileList):
            fullfn = os.path.join(dataDir, fn)
            if not os.path.exists(fullfn):
                print("Download file \"%s\"." % (fn))
                tmpfn = fullfn + ".tmp"
                url = os.path.join(fileSource, fn)
                rc, out = Util.shellCallWithRetCode("/usr/bin/wget -O \"%s\" %s" % (tmpfn, url))
                if rc != 0 and rc != 8:
                    # ignore "file not found" error (8) since rsyncSource/fileSource may be different servers
                    raise Exception("download %s failed" % (url))
                os.rename(tmpfn, fullfn)
            else:
                print("File \"%s\" exists." % (fn))
            MUtil.progress_changed(sock, PROGRESS_STAGE_1 + PROGRESS_STAGE_2 * i // total)
        MUtil.progress_changed(sock, PROGRESS_STAGE_1 + PROGRESS_STAGE_2)

        # stage3: rsync
        Util.cmdExec("/usr/bin/rsync", "-a", "-z", "--delete", rsyncSource, dataDir)

        # report full progress
        MUtil.progress_changed(sock, 100)
    finally:
        sock.close()


def _makeDirAndGetFileList(rsyncSource, dataDir):
    out = Util.shellCall("/usr/bin/rsync -a --no-motd --list-only %s 2>&1" % (rsyncSource))

    ret = []
    for line in out.split("\n"):
        m = re.match("(\\S{10}) +([0-9,]+) +(\\S+ \\S+) (.+)", line)
        if m is None:
            continue
        modstr = m.group(1)
        filename = m.group(4)
        if filename.startswith("."):
            continue
        if " -> " in filename:
            continue

        if modstr.startswith("d"):
            Util.ensureDir(os.path.join(dataDir, filename))
        else:
            ret.append(filename)

    return ret


class MUtil:

    @staticmethod
    def connect():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect("/run/mirrors/api.socket")
        return sock

    @staticmethod
    def progress_changed(sock, progress):
        sock.send(json.dumps({
            "message": "progress",
            "data": {
                "progress": progress,
            },
        }).encode("utf-8"))
        sock.send(b'\n')


class Util:

    @staticmethod
    def randomSorted(tlist):
        return sorted(tlist, key=lambda x: random.random())

    @staticmethod
    def ensureDir(dirname):
        if not os.path.exists(dirname):
            os.makedirs(dirname)

    @staticmethod
    def cmdExec(cmd, *kargs):
        # call command to execute frontend job
        #
        # scenario 1, process group receives SIGTERM, SIGINT and SIGHUP:
        #   * callee must auto-terminate, and cause no side-effect
        #   * caller must be terminate AFTER child-process, and do neccessary finalization
        #   * termination information should be printed by callee, not caller
        # scenario 2, caller receives SIGTERM, SIGINT, SIGHUP:
        #   * caller should terminate callee, wait callee to stop, do neccessary finalization, print termination information, and be terminated by signal
        #   * callee does not need to treat this scenario specially
        # scenario 3, callee receives SIGTERM, SIGINT, SIGHUP:
        #   * caller detects child-process failure and do appopriate treatment
        #   * callee should print termination information

        # FIXME, the above condition is not met, FmUtil.shellExec has the same problem

        ret = subprocess.run([cmd] + list(kargs), universal_newlines=True)
        if ret.returncode > 128:
            time.sleep(1.0)
        ret.check_returncode()

    @staticmethod
    def shellCall(cmd):
        # call command with shell to execute backstage job
        # scenarios are the same as FmUtil.cmdCall

        ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             shell=True, universal_newlines=True)
        if ret.returncode > 128:
            # for scenario 1, caller's signal handler has the oppotunity to get executed during sleep
            time.sleep(1.0)
        if ret.returncode != 0:
            ret.check_returncode()
        return ret.stdout.rstrip()

    @staticmethod
    def shellCallWithRetCode(cmd):
        ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             shell=True, universal_newlines=True)
        if ret.returncode > 128:
            time.sleep(1.0)
        return (ret.returncode, ret.stdout.rstrip())


###############################################################################

if __name__ == "__main__":
    main()
