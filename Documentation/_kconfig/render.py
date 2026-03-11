#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to you under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Generate RST documentation from Kconfig files using kconfiglib.
# Extracts ---help--- sections and creates per-symbol and per-choice pages.
#

import argparse
import operator
import os
import shutil
import sys
import tempfile

import kconfiglib
from jinja2 import Environment, FileSystemLoader


def choice_id(choice):
    return f"choice_{choice.kconfig.unique_choices.index(choice)}"


def choice_desc(choice):
    desc = "choice"
    if choice.name:
        desc += " " + choice.name
    for node in choice.nodes:
        if node.prompt:
            desc += ": " + node.prompt[0]
            break
    return desc


def rst_link(sc):
    if isinstance(sc, kconfiglib.Symbol):
        if sc.nodes:
            return rf"\ :option:`CONFIG_{sc.name}`"
    elif isinstance(sc, kconfiglib.Choice):
        return rf"\ :ref:`<{choice_desc(sc)}> <{choice_id(sc)}>`"
    return kconfiglib.standard_sc_expr_str(sc)


def expr_str(expr):
    return kconfiglib.expr_str(expr, rst_link)


def top_to_node(node):
    path = []
    while node.parent is not node.kconfig.top_node:
        node = node.parent
        path = [node] + path
    return path


def has_non_trivial_dep(sc):
    """Return True if the symbol/choice has a non-trivial direct dependency."""
    if sc.direct_dep is None:
        return False
    return sc.direct_dep is not sc.kconfig.y


def has_rev_dep(sym):
    """Return True if the symbol has a non-trivial reverse dependency."""
    if not hasattr(sym, "rev_dep") or sym.rev_dep is None:
        return False
    return sym.rev_dep is not sym.kconfig.n


def escape_help(sc):
    """Escape RST-special chars in help text for Symbols and Choices."""
    for node in sc.nodes:
        if node.help:
            node.help = (
                node.help.replace("`", r"\`")
                .replace("*", r"\*")
                .replace("<", r"\<")
                .replace("|", r"\|")
            )


def setup_stub_dirs(topdir):
    """
    Create temporary directories with stub Kconfig files required by the
    root Kconfig. Returns (bindir, appsdir, externaldir) paths.
    The source tree is never modified.
    """
    tmp = tempfile.mkdtemp(prefix="nuttx_kconfig_docs_")

    bindir = os.path.join(tmp, "bindir")
    os.makedirs(os.path.join(bindir, "arch", "dummy"), exist_ok=True)
    os.makedirs(os.path.join(bindir, "boards", "dummy"), exist_ok=True)
    os.makedirs(os.path.join(bindir, "drivers", "platform"), exist_ok=True)
    for path in [
        os.path.join(bindir, "arch", "dummy", "Kconfig"),
        os.path.join(bindir, "boards", "dummy", "Kconfig"),
        os.path.join(bindir, "drivers", "platform", "Kconfig"),
    ]:
        with open(path, "w") as f:
            f.write("")

    appsdir = os.path.join(tmp, "apps")
    os.makedirs(appsdir, exist_ok=True)
    with open(os.path.join(appsdir, "Kconfig"), "w") as f:
        f.write("")

    externaldir = os.path.join(tmp, "external")
    os.makedirs(externaldir, exist_ok=True)
    with open(os.path.join(externaldir, "Kconfig"), "w") as f:
        f.write("")

    return tmp, bindir, appsdir, externaldir


def main():
    parser = argparse.ArgumentParser(
        description="Generate RST documentation from Kconfig files"
    )
    parser.add_argument(
        "--report-missing",
        action="store_true",
        help="Report CONFIG symbols that have no ---help--- text",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    topdir = os.path.realpath(os.path.join(script_dir, "..", ".."))

    tmpdir, bindir, appsdir, externaldir = setup_stub_dirs(topdir)
    try:
        os.environ["TOPDIR"] = topdir
        os.environ["ARCH"] = "dummy"
        os.environ["BINDIR"] = bindir
        os.environ["APPSDIR"] = appsdir
        os.environ["APPSBINDIR"] = appsdir
        os.environ["EXTERNALDIR"] = externaldir
        os.environ["srctree"] = topdir

        os.chdir(topdir)
        kconf = kconfiglib.Kconfig("Kconfig", warn=False)

        kconfig_rst_dir = os.path.join(topdir, "Documentation", "kconfig")
        os.makedirs(kconfig_rst_dir, exist_ok=True)

        env = Environment(loader=FileSystemLoader(script_dir))
        env.globals["kconfiglib"] = kconfiglib
        env.globals["expr_str"] = expr_str
        env.globals["rst_link"] = rst_link
        env.globals["top_to_node"] = top_to_node
        env.globals["choice_desc"] = choice_desc
        env.globals["choice_id"] = choice_id
        env.globals["has_non_trivial_dep"] = has_non_trivial_dep
        env.globals["has_rev_dep"] = has_rev_dep
        _type_to_str = getattr(kconfiglib, "TYPE_TO_STR", {})
        env.globals["type_str"] = lambda sc: _type_to_str.get(
            getattr(sc, "orig_type", None), "unknown"
        )

        sym_template = env.get_template("sym.jinja")
        choice_template = env.get_template("choice.jinja")
        index_template = env.get_template("index.jinja")

        missing_help = []

        for sym in kconf.unique_defined_syms:
            escape_help(sym)
            if args.report_missing and not any(n.help for n in sym.nodes):
                missing_help.append(f"CONFIG_{sym.name}")
            with open(
                os.path.join(kconfig_rst_dir, f"CONFIG_{sym.name}.rst"), "w"
            ) as rst_f:
                rst_f.write(sym_template.render(sym=sym))

        for choice in kconf.unique_choices:
            escape_help(choice)
            with open(
                os.path.join(kconfig_rst_dir, f"{choice_id(choice)}.rst"), "w"
            ) as rst_f:
                rst_f.write(choice_template.render(choice=choice))

        with open(os.path.join(kconfig_rst_dir, "index.rst"), "w") as rst_f:
            rst_f.write(
                index_template.render(
                    syms=sorted(
                        kconf.unique_defined_syms,
                        key=operator.attrgetter("name"),
                    ),
                )
            )

        if args.report_missing and missing_help:
            print("CONFIG symbols without ---help--- text:", file=sys.stderr)
            for name in sorted(missing_help):
                print(f"  {name}", file=sys.stderr)
            print(
                f"\nTotal: {len(missing_help)} symbols",
                file=sys.stderr,
            )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
