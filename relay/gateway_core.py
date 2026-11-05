"""Pure helpers for tak_gateway (no I/O, unit-testable)."""
import io
import zipfile
from xml.sax.saxutils import escape

MAX_STREAM_BUF = 256 * 1024


def split_cot_stream(buf: bytearray) -> list:
    """Remove and return every complete <event ...>...</event> document from buf.

    TAK streams are concatenated CoT documents, optionally with an XML declaration
    and whitespace between them. Incomplete trailing data stays in buf. A buffer
    that grows past MAX_STREAM_BUF without a complete event is discarded.
    """
    out = []
    end_tag = b"</event>"
    while True:
        i = buf.find(end_tag)
        if i < 0:
            break
        j = i + len(end_tag)
        doc = bytes(buf[:j]).strip()
        del buf[:j]
        s = doc.find(b"<event")
        if s >= 0:
            out.append(doc[s:] if not doc.startswith(b"<?xml") else doc)
    if len(buf) > MAX_STREAM_BUF:
        buf.clear()
    return out


def prometheus_text(counters: dict, gauges: dict) -> str:
    """Prometheus text exposition. Keys may carry labels: 'name{a="b"}'."""
    # One "# TYPE" line per metric, before all of its series: Prometheus rejects the whole scrape
    # when a metric has a second TYPE line.
    lines, typed = [], set()
    for kind, metrics in (("counter", counters), ("gauge", gauges)):
        for name, v in sorted(metrics.items()):
            base = name.split("{")[0]
            if base not in typed:
                typed.add(base)
                lines.append(f"# TYPE {base} {kind}")
            lines.append(f"{name} {v}")
    return "\n".join(lines) + "\n"


def atak_data_package(host: str, port: int = 8087, proto: str = "tcp", name: str = "EFDI backbone") -> bytes:
    """ATAK/WinTAK mission package that adds one streaming connection (import it in the client).

    Format written from memory of the TAK preference-package layout; verify on the
    target client before relying on it.
    """
    pref = (
        "<?xml version='1.0' encoding='ASCII' standalone='yes'?>\n"
        "<preferences>\n"
        '  <preference version="1" name="cot_streams">\n'
        '    <entry key="count" class="class java.lang.Integer">1</entry>\n'
        f'    <entry key="description0" class="class java.lang.String">{escape(name)}</entry>\n'
        '    <entry key="enabled0" class="class java.lang.Boolean">true</entry>\n'
        f'    <entry key="connectString0" class="class java.lang.String">{escape(host)}:{int(port)}:{escape(proto)}</entry>\n'
        "  </preference>\n"
        "</preferences>\n"
    )
    manifest = (
        '<MissionPackageManifest version="2"><Configuration>'
        '<Parameter name="uid" value="efdi-backbone-connection"/>'
        '<Parameter name="name" value="EFDI-backbone-connection.zip"/>'
        '<Parameter name="onReceiveImport" value="true"/>'
        '<Parameter name="onReceiveDelete" value="true"/>'
        '</Configuration><Contents>'
        '<Content ignore="false" zipEntry="EFDI/efdi-backbone.pref"/>'
        '</Contents></MissionPackageManifest>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("MANIFEST/manifest.xml", manifest)
        z.writestr("EFDI/efdi-backbone.pref", pref)
    return buf.getvalue()
