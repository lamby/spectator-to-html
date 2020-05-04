import os
import re
import sys
import json
import time
import jinja2
import shutil
import pickle
import hashlib
import logging
import requests
import itertools
import subprocess

from xdg.BaseDirectory import save_cache_path


re_widont_html = re.compile(
    r"([^<>\s])\s+([^<>\s]+\s*)(</?(?:address|blockquote|br|dd|div|dt|fieldset|form|h[1-6]|li|noscript|p|td|th)[^>]*>|$)",
    re.IGNORECASE,
)


def widont(txt):
    def cb_widont(m):
        return "{}&nbsp;{}{}".format(*m.groups())

    return re_widont_html.sub(cb_widont, txt)


class BaseToMobi:
    def __init__(self):
        self.epoch = time.time() - 3600
        self.session = requests.Session()

    def generate_mobi(self, tempdir):
        self.log.info("Generating magazine in %s", tempdir)

        with open(os.path.join(tempdir, "context.json"), "w") as f:
            json.dump(self.context, f, indent=2)

        assert self.context[
            "articles"
        ], "No articles downloaded; please check {}".format(self.BASE_URL)

        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))

        self.context["tempdir"] = tempdir
        self.context["grouped"] = [
            (x, list(y))
            for x, y in itertools.groupby(
                self.context["articles"], lambda x: x["subsection"]
            )
        ]

        self.save_image_to(
            self.context["cover"], os.path.join(tempdir, "cover.jpg")
        )

        for x in ("index.html", "toc.html", "style.css"):
            val = env.get_template(x).render(**self.context)
            with open(os.path.join(tempdir, x), "w") as f:
                f.write(val)

        # Download article images
        for x in self.context["articles"]:
            if x["image"] is None:
                continue

            target = os.path.join(tempdir, "{}.jpg".format(x["idx"]))
            self.save_image_to(x["image"], target)

        # Hide kindlegen output by default
        stdout, stderr = subprocess.PIPE, subprocess.PIPE
        if self.verbosity >= 2:
            stdout, stderr = None, None

        subprocess.call(
            (
                "kindlegen/kindlegen",
                "-verbose",
                os.path.join(tempdir, "index.html"),
            ),
            stdout=stdout,
            stderr=stderr,
        )

        if not self.filename:
            self.filename = "{}_{}.mobi".format(
                self.PREFIX,
                self.context["date"].replace(" ", "_")
            )

        self.log.info("Saving output to %s", self.filename)

        shutil.move(os.path.join(tempdir, "index.mobi"), self.filename)

    def save_image_to(self, url, target):
        self.log.debug("Downloading %s to %s", url, target)

        with open(target, "wb") as f:
            for x in self.get(url).iter_content(chunk_size=128):
                f.write(x)

        self.log.debug("Resizing and resampling %s", target)
        subprocess.check_call(
            (
                "convert",
                target,
                "-resize",
                "800x",
                "-set",
                "colorspace",
                "Gray",
                "-separate",
                "-average",
                "-quality",
                "60%",
                target,
            )
        )

    def setup_logging(self):
        self.log = logging.getLogger()
        self.log.setLevel(
            {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}[
                self.verbosity
            ]
        )

        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime).19s %(levelname).1s %(message)s")
        )
        self.log.addHandler(handler)

    def get(self, url, **kwargs):
        self.log.info("Downloading %s", url)

        h = hashlib.sha1()
        h.update(url.encode("utf-8"))
        for k, v in kwargs.items():
            h.update(k.encode("utf-8"))
            h.update(v.encode("utf-8"))

        filename = os.path.join(save_cache_path(self.NAME), h.hexdigest())

        if (
            os.path.exists(filename)
            and os.path.getmtime(filename) > self.epoch
        ):
            with open(filename, "rb") as f:
                return pickle.load(f)

        response = self.session.get(
            url, headers={"User-agent": "Mozilla/5.0"}, params=kwargs
        )
        response.raise_for_status()

        with open(filename, "wb") as f:
            pickle.dump(response, f)

        return response
