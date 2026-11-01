"""A right or remedy named in a sentence must be named by the source units the sentence cites.

Measured 2026-10-30: "bildirim şartına uymamak kıdem tazminatı gibi diğer haklarınıza engel olmaz" was approved by the model
checker although the cited unit (4857 m. 17) speaks of Articles 18-21 and never of the severance pay. The sentence may well be
true, but a true sentence that its source does not say is a sentence without a source. Only distinctive names of rights are
listed; a source may name the same right in the statute's own words, which the evidence patterns accept. This is an additional
mechanical gate, never a proof of support.
"""

import re

from api.ai.search_plan import normalize

# (name, pattern of the claim, pattern the cited evidence must match). Both run on `normalize`d text.
_TERMS: tuple[tuple[str, re.Pattern, re.Pattern], ...] = tuple(
    (name, re.compile(claim), re.compile(evidence)) for name, claim, evidence in (
        ("kıdem", r"\bkıdem", r"kıdem"),
        ("ihbar", r"\bihbar", r"ihbar|bildirim süre|bildirim şart|önceden bildir|bildirimde bulun|bildirim yap"),
        ("iştirak nafakası", r"\biştirak", r"iştirak"),
        ("yoksulluk nafakası", r"\byoksullu[kğ]", r"yoksullu[kğ]"),
        ("tedbir nafakası", r"\btedbir nafaka", r"tedbir|geçici önlem"),
        ("işe iade", r"\bişe iade",
         r"işe iade|işe başlat|geçersizliği|iş güvencesi|geçerli (?:bir )?(?:sebep|neden)|fesih bildirimine itiraz|feshin geçersiz"),
        ("manevi tazminat", r"\bmanevi", r"manevi"),
        ("yıllık izin", r"\byıllık (?:ücretli )?izin", r"yıllık (?:ücretli )?izin"),
        ("fazla çalışma", r"\bfazla (?:çalışma|mesai)", r"fazla (?:çalışma|mesai|sürelerle)"),
        ("katılma alacağı", r"\bkatılma alacağ", r"katılma alacağ|mal rejimi"),
        ("velayet", r"\bvelayet", r"velayet"),
        # Time limits are the most consequential thing a sentence can add: a "zamanaşımı" is not a "hak düşürücü süre".
        ("zamanaşımı", r"\bzamanaşım|\bzaman aşım", r"zamanaşım|zaman aşım"),
        ("hak düşürücü süre", r"\bhak düşürücü", r"hak düşürücü|hakkı düşer|hak düşer|düşer"),
        ("faiz", r"\bfaiz", r"faiz"),
        ("vekâlet ücreti", r"\bvekalet ücret|\bvekâlet ücret", r"vekalet ücret|vekâlet ücret"),
        ("depozito", r"\bdepozito|\bkira güvence", r"depozito|güvence"),
        ("tahliye", r"\btahliye", r"tahliye|boşalt"),
        ("haciz", r"\bhaciz", r"haciz"),
        ("ihtiyati tedbir", r"\bihtiyati tedbir", r"ihtiyati tedbir|tedbir"),
        ("istinaf", r"\bistinaf", r"istinaf"),
        ("temyiz", r"\btemyiz", r"temyiz"),
    ))


def terms_added(claim: str, evidence: str) -> list[str]:
    """Names of rights the claim uses that none of the cited evidence (units and source heading) mentions."""
    claim_text, evidence_text = normalize(claim), normalize(evidence)
    return [name for name, in_claim, in_evidence in _TERMS
            if in_claim.search(claim_text) and not in_evidence.search(evidence_text)]
