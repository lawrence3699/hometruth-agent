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


def rea_detail_page(rid, title_line1, suburb, pc, price, avail="Available now", rooms="2 bedrooms 1 bathroom 1 car space"):
    """realestate.com.au 单套详情页的骨架：标题、价格、入住、描述（og:description）、设施、头图 + 缩略图 + 户型图缩略图、中介、相似房源。"""
    h = lambda k: f"{rid}{k}".rjust(64, "0")[-64:]
    imgs = [f"https://i2.au.reastatic.net/800x600-format=webp/{h(1)}/image.jpg", f"https://i2.au.reastatic.net/360x270-format=avif/{h(2)}/image.jpg",
            f"https://i2.au.reastatic.net/360x270-format=avif/{h(3)}/image.jpg"]
    page = (f'<html><head><title data-rh="true">{title_line1}, {suburb}, NSW {pc} - Apartment for Rent - realestate.com.au</title>'
            f'<meta property="og:description" content="Bright corner unit.&lt;br/&gt;&lt;br/&gt;Walk to the light rail.&lt;br/&gt;" ></head><body>'
            f'<div data-testid="HeroMosaic"><div role="button" tabindex="0" aria-label="Preview property images, {title_line1}"><picture>'
            f'<source srcset="{imgs[0]}"><img alt="x, image 1 of 9" src="{imgs[0].replace("-format=webp", "")}"></picture></div>'
            f'<span data-testid="countIcon" class="media-type-bar__count">9</span><span data-testid="countIcon" class="media-type-bar__text">Images</span></div>'
            f'<div data-testid="hero-thumbnails"><div role="button" aria-label="Preview property image 2 of 9" tabindex="0"><picture>'
            f'<source srcset="{imgs[1]}" type="image/avif"><img src="{imgs[1].replace("-format=avif", "")}"></picture></div></div>'
            f'<ul aria-label="Apartment  with {rooms}"><li aria-label="2 bedrooms"></li></ul>'
            f'<span class="property-price property-info__price">{price}</span><div class="property-info__footer-content"><p class="T">{avail}</p></div>'
            f'<div data-testid="PropertyDescription"><h2 class="T">SUNNY CORNER UNIT</h2></div>'
            f'<div data-testid="all-property-features-section" class="S"><div><h3>Rental information</h3><div><p>Pets allowed</p></div></div>'
            f'<div><h3>Heating &amp; cooling</h3><div><p>Split-system air con</p></div></div></div><button>Show less</button>'
            f'<div class="floorplans-tours"><picture><source srcset="{imgs[2]}" type="image/avif"><img alt="Property floorplan" src="{imgs[2].replace("-format=avif", "")}"></picture></div>'
            f'<div class="contact-agent-panel"><div class="styles__AgencyOrProjectNonLink-sc-1 x">Sample Agency</div><small>1 Ellery Place, NSW 2000</small></div>'
            f'<div data-testid="enquiry-form"></div>'
            f'<ul aria-label="Apartment  with 4 bedrooms"><span class="property-price">$2,000 per week</span>'  # 相似房源：不能读进来
            f'<a class="LinkBase styles__AgencyOrProjectNameLink-sc-1 y">Other Agency</a></ul></body></html>')
    return page, imgs, f"https://www.realestate.com.au/property-apartment-nsw-{suburb.lower()}-{rid}"


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

    def test_add_only_takes_new_cards(self):
        cards, _ = isp.parse([self.tmp])
        have = {isp.norm_key("4", "12", "Birchwood Street", "Kensington"): "domain/19000001"}  # 这套已经在库里
        got = isp.new_cards(cards, have)
        self.assertEqual([(c["site"], c["id"]) for c in got], [("rea", 901000001)])  # 同地址的 REA 那张、没门牌 / 没周租 / 已出租的都不要
        self.assertEqual(isp.new_cards(cards, dict(have, **{"x": "rea/901000001"})), [])
        (self.tmp / "REA Alder exact oldest-first page 03.mhtml").write_text("x", encoding="utf-8")  # 首轮文件名不带 realestate，被漏掉过
        (self.tmp / "REA property 902000009.mhtml").write_text("x", encoding="utf-8")                # 单套详情页走 details，不当搜索页
        names = {f.name for f in isp.source_files([self.tmp])}
        self.assertIn("REA Alder exact oldest-first page 03.mhtml", names)
        self.assertNotIn("REA property 902000009.mhtml", names)

    def test_listing_json_is_card_only_and_honest(self):
        cards, _ = isp.parse([self.tmp])
        c = next(c for c in cards if c["id"] == 19000001)
        c.update(lat=-33.91, lng=151.22, geocode={"source": "test", "precision": "street", "query": "x"})
        L = isp.to_listing(c)
        self.assertEqual((L["site"], L["card_only"], L["unit"], L["streetNumber"], L["street"], L["type"]), ("domain", True, "4", "12", "Birchwood Street", "Apartment / Unit / Flat"))
        self.assertEqual((L["description"], L["stats"], L["headline"], L["medianRent"]), ([], {}, "", None))
        self.assertTrue(all(s.get("embedded") for s in L["slides"]))
        json.dumps(L)

    def test_detail_page_becomes_a_rich_listing(self):
        d = self.tmp / "details"
        d.mkdir()
        page, imgs, origin = rea_detail_page(902000001, "A-Fully Furnish-L6A/39-41 ALDER LANE", "Redfern", "2016", "$900 per week")
        (d / "REA property 902000001.mhtml").write_text(mhtml(page, imgs, origin), encoding="utf-8")
        page, imgs, origin = rea_detail_page(902000002, "3B2B/6 Dunmore Row", "Redfern", "2016", "$1,200 per week", avail="Available 08 Feb 2027")
        (d / "REA property 902000002.mhtml").write_text(mhtml(page, imgs, origin), encoding="utf-8")
        page, imgs, origin = rea_detail_page(902000003, "Redfern - address available on request", "Redfern", "2016", "$800 per week")
        (d / "REA property 902000003.mhtml").write_text(mhtml(page.replace("<title data-rh=\"true\">Redfern - address available on request, Redfern, NSW 2016",
                                                                          "<title>Redfern - address available on request"), imgs, origin), encoding="utf-8")
        cards, blobs = isp.parse_details([d])
        by = {c["id"]: c for c in cards}
        self.assertEqual(set(by), {902000001, 902000002})  # 没地址的那页跳过
        c = by[902000001]
        self.assertEqual((c["line1"], c["suburb"], c["postcode"], c["beds"], c["baths"], c["parking"], c["agency"]),
                         ("L6A/39-41 Alder Lane", "Redfern", "2016", "2", "1", "1", "Sample Agency"))
        self.assertIn("ad words", c["line1_note"])
        self.assertEqual(isp.weekly(c["price"]), 900)  # 不是相似房源的 $2,000
        self.assertEqual((c["headline"], c["description"], c["features"]), ("SUNNY CORNER UNIT", ["Bright corner unit.", "", "Walk to the light rail."], ["Pets allowed", "Split-system air con"]))
        self.assertEqual([(s["type"], s["w"]) for s in c["slides"]], [("image", 800), ("image", 360), ("floorplan", 360)])
        self.assertEqual(c["availableText"], "Available now")
        self.assertEqual(by[902000002]["availableFrom"], "2027-02-08")
        self.assertEqual(by[902000002]["line1"], "6 Dunmore Row")  # '3B2B' 是卧室 / 卫生间，不是单元号
        c.update(lat=-33.89, lng=151.20, geocode={"source": "test", "precision": "street", "query": "x"})
        L = isp.to_listing(c)
        self.assertNotIn("card_only", L)
        self.assertEqual(L["stats"]["availableFrom"], c["availableFrom"])
        self.assertEqual([(s["type"], s["thumb"]) for s in L["slides"]], [("image", False), ("image", True), ("floorplan", True)])
        self.assertIn("listing page saved by the user", L["source"])
        self.assertEqual(isp.as_webp(isp.as_webp(PNG))[:4], b"RIFF")
        json.dumps(L)

    def test_address_splitting(self):
        self.assertEqual(isp.split_address("Unit 4/9 Alder Lane"), ("4", "9", "Alder Lane"))
        self.assertEqual(isp.split_address("A309/25 Caldera Avenue"), ("A309", "25", "Caldera Avenue"))
        self.assertEqual(isp.split_address("10/17-21 Fenwick Street"), ("10", "17-21", "Fenwick Street"))
        self.assertEqual(isp.split_address("1.11/2-8 Dunmore Row"), ("1.11", "2-8", "Dunmore Row"))
        self.assertIsNone(isp.split_address("WeChat: X L2/ 8 Alder Lane"))
        self.assertIsNone(isp.split_address("Fully Furnished-L1D/107 Alder Lane"))
        self.assertIsNone(isp.split_address("Ellery Place"))
        self.assertEqual(isp.split_address("L1+2A/109-123 Fenwick St"), ("L1+2A", "109-123", "Fenwick St"))
        self.assertEqual(isp.clean_line1("FullyFurnish-L1D/107 Alder Lane")[0], "L1D/107 Alder Lane")
        self.assertEqual(isp.tidy_street("2B/12 Caldera road", None)[0], "2B/12 Caldera Road")

    def test_redact_contacts(self):
        self.assertEqual(isp.redact("Call 0400 000 000 or VX: +61 400000000, WeChat：sample_id9"),
                         "Call [contact removed] or VX: [contact removed], WeChat：[contact removed]")
        self.assertEqual(isp.redact("Email jo@example.com today"), "Email [contact removed] today")
        self.assertEqual(isp.redact("10-12 Fenwick Street, $1,100 per week, built 2019"), "10-12 Fenwick Street, $1,100 per week, built 2019")

    def test_weekly(self):
        self.assertEqual(isp.weekly("$1,050 per week"), 1050)
        self.assertEqual(isp.weekly("$700 - $750 per week"), 700)
        self.assertIsNone(isp.weekly("Contact agent"))
        self.assertIsNone(isp.weekly("$50 per week"))


if __name__ == "__main__":
    unittest.main()
