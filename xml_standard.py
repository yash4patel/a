from lxml import etree


class Standard:
    """
    Minimal Standard XML dialect with only:
    - to_dict
    - from_dict
    """

    def __init__(self, xml_or_dict):
        if isinstance(xml_or_dict, dict):
            self.root = self.from_dict(xml_or_dict)
        else:
            self.root = etree.fromstring(xml_or_dict.encode("utf-8"))

    def to_dict(self):
        """Convert XML tree to dict of /a/b/c pathspec -> value."""
        result = {}

        def recurse(node, path):
            new_path = f"{path}/{node.tag}"
            if len(node) == 0 and node.text:
                txt = node.text.strip()
                if txt:
                    result[new_path] = txt
            for child in node:
                recurse(child, new_path)

        recurse(self.root, "")
        return result

    def from_dict(self, d):
        """Convert dict to XML tree."""
        root_tag = list(d.keys())[0].strip("/").split("/")[0]
        root = etree.Element(root_tag)

        for path, value in d.items():
            parts = path.strip("/").split("/")
            current = root
            for tag in parts[1:]:
                existing = current.find(tag)
                if existing is None:
                    current = etree.SubElement(current, tag)
                else:
                    current = existing
            current.text = value

        return root

    def __str__(self):
        return etree.tostring(self.root, pretty_print=True).decode("utf-8")
