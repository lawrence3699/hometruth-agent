# -*- coding: utf-8 -*-
"""scripts/import_saved_pages.py：用户存的单文件网页（mhtml）→ 卡片 → 房源 JSON。夹具全是虚构街名（data/streets.json）和假编号、假图片。"""
import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("import_saved_pages", ROOT / "scripts" / "import_saved_pages.py")
isp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isp)

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def domain_card(lid, line1, suburb, pc, price, beds="2", tag=""):
    img = f"https://rimh2.domainstatic.com.au/sig=/1440x1080/filters:format(webp):quality(35)/{lid}_1_1_261014_022844-w745-h494"
    slug = f"https://www.domain.com.au/{line1.lower().replace('/', '-').replace(' ', '-')}-{suburb.lower()}-nsw-{pc}-{lid}"
    return (f'<li data-testid="listing-{lid}"><div data-testid="listing-card-wrapper-premiumplus"><div data-testid="listing-card-branding">'
            f'<span data-testid="listing-card-brand-name">Example Realty</span></div>'
            f'<a href="{slug}"><picture><source srcset="{img}"><img src="{img.replace("1440x1080", "720x540")}"></picture></a>'
            f'<span>1 / 6</span>' + (f'<span data-testid="listing-card-tag">{tag}</span>' if tag else "") +
            f'<p data-testid="listing-card-price" class="x">{price} </p><a href="{slug}"><h2 data-testid="address-wrapper">'
            f'<span data-testid="address-line1">{line1},&nbsp;</span><span data-testid="address-line2"><span>{suburb}</span></span></h2></a>'
            f'<div data-testid="listing-card-features-wrapper"><div data-testid="property-features"><div data-testid="property-features-wrapper">'
            f'<span data-testid="property-features-feature"><span data-testid="property-features-text-container">{beds}<!-- --> <span data-testid="property-features-text">Beds</span></span><svg></svg></span>'
            f'<span data-testid="property-features-feature"><span data-testid="property-features-text-container">1<!-- --> <span data-testid="property-features-text">Bath</span></span><svg></svg></span>'
            f'</div></div><div><span>Apartment / Unit / Flat</span></div></div></div></li>'), img


def rea_card(rid, line1, suburb, pc, price):
    h = f"{rid:064d}"[-64:]
    img = f"https://i2.au.reastatic.net/800x600/{h}/image.jpg"
    return (f'<article class="results-card residential-card " aria-label="{line1}, {suburb}" data-testid="ResidentialCard">'
            f'<img class="branding__image" alt="Sample Agency" src="x"><div class="property-image" data-testid="PropertyImage" data-url="{img}">'
            f'<img class="property-image__img " alt="{line1}, {suburb}, NSW {pc}" src="{img}"></div>'
            f'<span class="property-price ">{price}</span><h2><a href="https://www.realestate.com.au/property-unit-nsw-{suburb.lower()}-{rid}">{line1}, {suburb}</a></h2>'
            f'<ul aria-label="Unit with 2 bedrooms"><li aria-label="2 bedrooms"><p class="Text__Typography-sc">2</p></li><li aria-label="1 bathroom"></li>'
            f'<li aria-label="1 car space"></li><p class="Text__Typography-sc">Unit</p></ul></article>'), img.replace("800x600", "800x600-format=webp")


def mhtml(page, images, origin):
    """和 Chrome 存的单文件网页同样的结构：multipart/related，第一段是 HTML，后面是图片（这里都用 base64）。"""
    b = "----MultipartBoundary--test"
    out = [f"From: <Saved by Blink>\nSnapshot-Content-Location: {origin}\nMIME-Version: 1.0\nContent-Type: multipart/related;\n\ttype=\"text/html\";\n\tboundary=\"{b}\"\n\n",
           f"--{b}\nContent-Type: text/html; charset=utf-8\nContent-Transfer-Encoding: base64\nContent-Location: {origin}\n\n{base64.encodebytes(page.encode()).decode()}\n"]
    for loc in images:
        out.append(f"--{b}\nContent-Type: image/png\nContent-Transfer-Encoding: base64\nContent-Location: {loc}\n\n{base64.b64encode(PNG).decode()}\n")
    out.append(f"--{b}--\n")
    return "".join(out)


class SavedPages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        c1, i1 = domain_card(19000001, "4/12 Birchwood Street", "Kensington", "2033", "$820 per week")
        c2, i2 = domain_card(19000002, "Caldera Avenue", "Kingsford", "2032", "$700 per week")           # 没门牌号
        c3, _ = domain_card(19000003, "7/3 Fenwick Street", "Randwick", "2031", "Contact agent")         # 没周租
        c4, i4 = domain_card(19000004, "9/1 Ellery Place", "Zetland", "2017", "$900 per week", tag="Deposit taken")
        page = "<html><body><ul>" + c1 + c2 + c3 + c4 + "</ul></body></html>"
        (self.tmp / "Apartments for Rent _ Domain - page 1.mhtml").write_text(
            mhtml(page, [i1, i2, i4], "https://www.domain.com.au/rent/?page=1"), encoding="utf-8")
        r1, ri1 = rea_card(901000001, "2/8 Dunmore Row", "Redfern", "2016", "$750 per week")
        r2, ri2 = rea_card(901000002, "4/12 Birchwood Street", "Kensington", "2033", "$815 per week")    # 同一地址也在 Domain
        (self.tmp / "Rental Properties - realestate.com.au.mhtml").write_text(
            mhtml("<html><body>" + r1 + r2 + "</body></html>", [ri1, ri2], "https://www.realestate.com.au/rent/list-1"), encoding="utf-8")

    def test_parse_both_sites_and_skip_reasons(self):
        cards, blobs = isp.parse([self.tmp])
        by = {(c["site"], c["id"]): c for c in cards}
        d = by[("domain", 19000001)]
        self.assertEqual((d["line1"], d["suburb"], d["postcode"], d["beds"], d["baths"], d["agency"], d["gallery_count"]),
                         ("4/12 Birchwood Street", "Kensington", "2033", "2", "1", "Example Realty", 6))
        self.assertEqual(isp.weekly(d["price"]), 820)
        self.assertTrue(d["slides"][0]["embedded"])
        self.assertEqual(isp.usable(by[("domain", 19000002)]), "no street number")
        self.assertEqual(isp.usable(by[("domain", 19000003)]), "no weekly price")
        self.assertEqual(isp.usable(by[("domain", 19000004)]), "deposit taken / leased")
        r = by[("rea", 901000001)]
        self.assertEqual((r["line1"], r["suburb"], r["postcode"], r["beds"], r["parking"], r["agency"]), ("2/8 Dunmore Row", "Redfern", "2016", "2", "1", "Sample Agency"))
        self.assertTrue(r["slides"][0]["embedded"])
        self.assertIn(("rea", 901000001, 1), blobs)

    def test_select_keeps_domain_when_both_sites_list_it(self):
        cards, _ = isp.parse([self.tmp])
        picked = isp.select(cards, 10, 10, {})
        ids = {(c["site"], c["id"]) for c in picked}
        self.assertIn(("domain", 19000001), ids)
        self.assertIn(("rea", 901000001), ids)
        self.assertNotIn(("rea", 901000002), ids)

    def test_listing_json_is_card_only_and_honest(self):
        cards, _ = isp.parse([self.tmp])
        c = next(c for c in cards if c["id"] == 19000001)
        c.update(lat=-33.91, lng=151.22, geocode={"source": "test", "precision": "street", "query": "x"})
        L = isp.to_listing(c)
        self.assertEqual((L["site"], L["card_only"], L["unit"], L["streetNumber"], L["street"], L["type"]), ("domain", True, "4", "12", "Birchwood Street", "Apartment / Unit / Flat"))
        self.assertEqual((L["description"], L["stats"], L["headline"], L["medianRent"]), ([], {}, "", None))
        self.assertTrue(all(s.get("embedded") for s in L["slides"]))
        json.dumps(L)

    def test_address_splitting(self):
        self.assertEqual(isp.split_address("Unit 4/9 Alder Lane"), ("4", "9", "Alder Lane"))
        self.assertEqual(isp.split_address("A309/25 Caldera Avenue"), ("A309", "25", "Caldera Avenue"))
        self.assertEqual(isp.split_address("10/17-21 Fenwick Street"), ("10", "17-21", "Fenwick Street"))
        self.assertEqual(isp.split_address("1.11/2-8 Dunmore Row"), ("1.11", "2-8", "Dunmore Row"))
        self.assertIsNone(isp.split_address("WeChat: X L2/ 8 Alder Lane"))
        self.assertIsNone(isp.split_address("Fully Furnished-L1D/107 Alder Lane"))
        self.assertIsNone(isp.split_address("Ellery Place"))

    def test_weekly(self):
        self.assertEqual(isp.weekly("$1,050 per week"), 1050)
        self.assertEqual(isp.weekly("$700 - $750 per week"), 700)
        self.assertIsNone(isp.weekly("Contact agent"))
        self.assertIsNone(isp.weekly("$50 per week"))


if __name__ == "__main__":
    unittest.main()
