from lights_out.ledger.evidence_ledger import EvidenceLedger, verify_chain


def test_chain_verifies_and_detects_tampering():
    led = EvidenceLedger()
    for i in range(5):
        led.append(actor="agent:x", action="a", subject=f"s{i}", autonomy_level="A2", payload={"i": i},
                   controls=("SOX-R2R-03",), ts=1000.0 + i)
    exported = led.export()
    assert verify_chain(exported) == (True, None)

    exported[2]["payload"]["i"] = 99          # tamper with an amount
    ok, bad = verify_chain(exported)
    assert ok is False and bad == 2

    exported = led.export()
    exported.pop(1)                            # delete a record
    ok, bad = verify_chain(exported)
    assert ok is False and bad == 1


def test_control_pull():
    led = EvidenceLedger()
    led.append(actor="a", action="post", subject="je-1", autonomy_level="A3", controls=("SOX-R2R-05",))
    led.append(actor="a", action="match", subject="r-1", autonomy_level="A3", controls=("SOX-R2R-03",))
    assert [e.subject for e in led.by_control("SOX-R2R-05")] == ["je-1"]
