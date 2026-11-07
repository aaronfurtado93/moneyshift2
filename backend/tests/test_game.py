import random

from tests.conftest import auth


def snap(client, g, who="host"):
    r = client.get(f"/api/games/{g['code']}", headers=auth(g[who]["token"]))
    assert r.status_code == 200, r.text
    return r.json()


def balances(client, g):
    return {p["name"]: p["balance"] for p in snap(client, g)["players"]}


def pay(client, g, who, to, amount, key=None):
    return client.post(
        f"/api/games/{g['code']}/transactions",
        headers=auth(g[who]["token"]),
        json={"to_id": g[to]["player_id"], "amount": amount, "key": key},
    )


def test_create_and_join(client, game):
    s = snap(client, game)
    assert [p["name"] for p in s["players"]] == ["Hana", "Ana", "Ben"]
    assert all(p["balance"] == 1000 for p in s["players"])
    assert s["me"]["role"] == "host"
    assert snap(client, game, "Ana")["me"]["role"] == "player"


def test_duplicate_name_rejected(client, game):
    r = client.post(f"/api/games/{game['code']}/join", json={"name": "ana"})
    assert r.status_code == 409


def test_pay_moves_money(client, game):
    assert pay(client, game, "Ana", "Ben", 250).status_code == 200
    b = balances(client, game)
    assert b["Ana"] == 750 and b["Ben"] == 1250


def test_cannot_overspend_or_pay_self(client, game):
    r = pay(client, game, "Ana", "Ben", 1001)
    assert r.status_code == 409 and r.json()["code"] == "insufficient"
    assert pay(client, game, "Ana", "Ana", 5).status_code == 400
    assert pay(client, game, "Ana", "Ben", 0).status_code == 400
    assert pay(client, game, "Ana", "Ben", -5).status_code == 400
    assert balances(client, game)["Ana"] == 1000


def test_idempotent_retry_does_not_double_charge(client, game):
    first = pay(client, game, "Ana", "Ben", 100, key="k1").json()
    second = pay(client, game, "Ana", "Ben", 100, key="k1").json()
    assert first["duplicate"] is False and second["duplicate"] is True
    assert balances(client, game)["Ana"] == 900


def test_auth_required(client, game):
    r = client.get(f"/api/games/{game['code']}")
    assert r.status_code == 401
    r = client.get(f"/api/games/{game['code']}", headers=auth("nope"))
    assert r.status_code == 401
    r = client.get("/api/games/ZZZZ", headers=auth(game["host"]["token"]))
    assert r.status_code == 404


def test_only_host_can_use_bank(client, game):
    h = auth(game["Ana"]["token"])
    body = {"player_id": game["Ana"]["player_id"], "amount": 500}
    assert client.post(f"/api/games/{game['code']}/bank/pay", headers=h, json=body).status_code == 403
    assert client.post(f"/api/games/{game['code']}/bank/collect", headers=h, json=body).status_code == 403
    assert balances(client, game)["Ana"] == 1000


def test_bank_pay_and_collect(client, game):
    h = auth(game["host"]["token"])
    body = {"player_id": game["Ana"]["player_id"], "amount": 200}
    assert client.post(f"/api/games/{game['code']}/bank/pay", headers=h, json=body).status_code == 200
    assert balances(client, game)["Ana"] == 1200
    body["amount"] = 1300
    r = client.post(f"/api/games/{game['code']}/bank/collect", headers=h, json=body)
    assert r.status_code == 409
    body["amount"] = 700
    assert client.post(f"/api/games/{game['code']}/bank/collect", headers=h, json=body).status_code == 200
    assert balances(client, game)["Ana"] == 500


def test_request_approve_and_deny(client, game):
    code = game["code"]
    ana = auth(game["Ana"]["token"])
    host = auth(game["host"]["token"])
    r1 = client.post(f"/api/games/{code}/requests", headers=ana, json={"amount": 300}).json()
    r2 = client.post(f"/api/games/{code}/requests", headers=ana, json={"amount": 50}).json()
    assert len(snap(client, game)["requests"]) == 2
    assert len(snap(client, game, "Ben")["requests"]) == 0  # not visible to other players
    # players cannot resolve
    bad = client.post(
        f"/api/games/{code}/requests/{r1['result']['id']}/resolve", headers=ana, json={"approve": True}
    )
    assert bad.status_code == 403
    ok = client.post(
        f"/api/games/{code}/requests/{r1['result']['id']}/resolve", headers=host, json={"approve": True}
    )
    assert ok.status_code == 200
    no = client.post(
        f"/api/games/{code}/requests/{r2['result']['id']}/resolve", headers=host, json={"approve": False}
    )
    assert no.status_code == 200
    assert balances(client, game)["Ana"] == 1300
    again = client.post(
        f"/api/games/{code}/requests/{r1['result']['id']}/resolve", headers=host, json={"approve": True}
    )
    assert again.status_code == 409
    assert snap(client, game)["requests"] == []


def test_undo_restores_balances_once(client, game):
    tx = pay(client, game, "Ana", "Ben", 400).json()["result"]
    host = auth(game["host"]["token"])
    url = f"/api/games/{game['code']}/transactions/{tx['id']}/reverse"
    assert client.post(url, headers=auth(game["Ana"]["token"])).status_code == 403
    assert client.post(url, headers=host).status_code == 200
    assert balances(client, game)["Ana"] == 1000 and balances(client, game)["Ben"] == 1000
    assert client.post(url, headers=host).status_code == 409
    s = snap(client, game)
    assert any(t["kind"] == "reversal" for t in s["transactions"])
    assert next(t for t in s["transactions"] if t["id"] == tx["id"])["reversed"] is True


def test_ended_game_rejects_changes(client, game):
    host = auth(game["host"]["token"])
    assert (
        client.post(f"/api/games/{game['code']}/end", headers=auth(game["Ana"]["token"])).status_code == 403
    )
    assert client.post(f"/api/games/{game['code']}/end", headers=host).status_code == 200
    assert pay(client, game, "Ana", "Ben", 10).status_code == 409
    assert client.post(f"/api/games/{game['code']}/join", json={"name": "Cam"}).status_code == 409


def test_money_is_conserved_under_random_play(client, game):
    """Sum of balances always equals starting money plus net bank payout."""
    rnd = random.Random(7)
    names = ["host", "Ana", "Ben"]
    host = auth(game["host"]["token"])
    code = game["code"]
    bank_net = 0
    for i in range(120):
        op = rnd.choice(["pay", "pay", "bank_pay", "bank_collect", "undo"])
        if op == "pay":
            a, b = rnd.sample(names, 2)
            pay(client, game, a, b, rnd.randint(1, 400), key=f"k{i}")
        elif op == "bank_pay":
            amt = rnd.randint(1, 300)
            who = rnd.choice(names)
            r = client.post(
                f"/api/games/{code}/bank/pay",
                headers=host,
                json={"player_id": game[who]["player_id"], "amount": amt},
            )
            assert r.status_code == 200
            bank_net += amt
        elif op == "bank_collect":
            amt = rnd.randint(1, 300)
            who = rnd.choice(names)
            r = client.post(
                f"/api/games/{code}/bank/collect",
                headers=host,
                json={"player_id": game[who]["player_id"], "amount": amt},
            )
            if r.status_code == 200:
                bank_net -= amt
        else:
            txs = [
                t for t in snap(client, game)["transactions"] if not t["reversed"] and t["kind"] != "reversal"
            ]
            if txs:
                t = rnd.choice(txs)
                r = client.post(f"/api/games/{code}/transactions/{t['id']}/reverse", headers=host)
                assert r.status_code == 200
                if t["from_id"] is None:
                    bank_net -= t["amount"]
                elif t["to_id"] is None:
                    bank_net += t["amount"]
        assert sum(balances(client, game).values()) == 3000 + bank_net


def test_websocket_pushes_events_and_catches_up(client, game):
    code = game["code"]
    tok = game["Ben"]["token"]
    with client.websocket_connect(f"/api/games/{code}/ws?token={tok}") as ws:
        assert ws.receive_json()["kind"] == "presence"
        hello = ws.receive_json()
        assert hello["kind"] == "hello"
        last = hello["seq"]
        pay(client, game, "Ana", "Ben", 50)
        msg = ws.receive_json()
        assert msg["kind"] == "event" and msg["type"] == "transaction" and msg["seq"] == last + 1
    # Ben "offline": more happens, then he reconnects asking for events after `last`
    pay(client, game, "Ana", "Ben", 25)
    with client.websocket_connect(f"/api/games/{code}/ws?token={tok}&since={last}") as ws:
        kinds = []
        for _ in range(4):
            m = ws.receive_json()
            kinds.append(m["kind"])
            if m["kind"] == "hello":
                break
        assert kinds.count("event") == 2  # the 50 and the 25 payments


def test_websocket_rejects_bad_token(client, game):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/games/{game['code']}/ws?token=bad"):
            pass


def test_banker_only_host_is_not_a_player(client):
    r = client.post(
        "/api/games", json={"host_name": "Bank", "starting_balance": 1000, "host_plays": False}
    ).json()
    code, host = r["code"], r
    ana = client.post(f"/api/games/{code}/join", json={"name": "Ana"}).json()
    ben = client.post(f"/api/games/{code}/join", json={"name": "Ben"}).json()
    g = {"code": code, "host": host, "Ana": ana, "Ben": ben}

    s = snap(client, g)
    me = s["me"]
    assert me["role"] == "host" and me["plays"] is False
    assert next(p for p in s["players"] if p["id"] == host["player_id"])["balance"] == 0

    # The bank cannot pay or ask; nobody can pay the bank-only host; bank ops can't target it.
    to_host = client.post(
        f"/api/games/{code}/transactions",
        headers=auth(ana["token"]),
        json={"to_id": host["player_id"], "amount": 10},
    )
    assert to_host.status_code == 400 and to_host.json()["code"] == "not_a_player"
    from_host = client.post(
        f"/api/games/{code}/transactions",
        headers=auth(host["token"]),
        json={"to_id": ana["player_id"], "amount": 10},
    )
    assert from_host.status_code == 400
    ask = client.post(f"/api/games/{code}/requests", headers=auth(host["token"]), json={"amount": 5})
    assert ask.status_code == 400
    for op in ("pay", "collect"):
        r2 = client.post(
            f"/api/games/{code}/bank/{op}",
            headers=auth(host["token"]),
            json={"player_id": host["player_id"], "amount": 5},
        )
        assert r2.status_code == 400

    # Normal bank operations on real players still work.
    ok = client.post(
        f"/api/games/{code}/bank/pay",
        headers=auth(host["token"]),
        json={"player_id": ana["player_id"], "amount": 250},
    )
    assert ok.status_code == 200
    assert balances(client, g)["Ana"] == 1250


def test_player_can_pay_the_bank(client, game):
    """What a scanned 'bank' QR code does: a player pays the bank themselves."""
    code = game["code"]
    ana = auth(game["Ana"]["token"])
    r = client.post(
        f"/api/games/{code}/transactions", headers=ana, json={"to_id": None, "amount": 150, "key": "tax1"}
    )
    assert r.status_code == 200 and r.json()["result"]["kind"] == "bank_collect"
    assert balances(client, game)["Ana"] == 850
    # idempotent, cannot overspend, host can undo
    dup = client.post(
        f"/api/games/{code}/transactions", headers=ana, json={"to_id": None, "amount": 150, "key": "tax1"}
    )
    assert dup.json()["duplicate"] is True and balances(client, game)["Ana"] == 850
    over = client.post(f"/api/games/{code}/transactions", headers=ana, json={"to_id": None, "amount": 5000})
    assert over.status_code == 409
    tx_id = r.json()["result"]["id"]
    undo = client.post(f"/api/games/{code}/transactions/{tx_id}/reverse", headers=auth(game["host"]["token"]))
    assert undo.status_code == 200 and balances(client, game)["Ana"] == 1000


def test_to_id_is_required(client, game):
    r = client.post(
        f"/api/games/{game['code']}/transactions", headers=auth(game["Ana"]["token"]), json={"amount": 5}
    )
    assert r.status_code == 422  # omitting to_id must not silently mean "the bank"


def test_amounts_must_be_whole_numbers(client, game):
    """Decimals, strings, booleans and non-positive values are refused everywhere money moves."""
    code = game["code"]
    ana, host = auth(game["Ana"]["token"]), auth(game["host"]["token"])
    ben_id = game["Ben"]["player_id"]
    bad_amounts = [2.5, 5.0, "5", "5.5", True, 0, -1, 10**10, None]
    for amount in bad_amounts:
        pay_r = client.post(
            f"/api/games/{code}/transactions", headers=ana, json={"to_id": ben_id, "amount": amount}
        )
        assert pay_r.status_code in (400, 422), (amount, pay_r.text)
        ask = client.post(f"/api/games/{code}/requests", headers=ana, json={"amount": amount})
        assert ask.status_code in (400, 422), (amount, ask.text)
        for op in ("pay", "collect"):
            b = client.post(
                f"/api/games/{code}/bank/{op}", headers=host, json={"player_id": ben_id, "amount": amount}
            )
            assert b.status_code in (400, 422), (op, amount, b.text)
    bad_start = client.post("/api/games", json={"host_name": "X", "starting_balance": 1500.5})
    assert bad_start.status_code == 422
    assert balances(client, game) == {"Hana": 1000, "Ana": 1000, "Ben": 1000}


def raw_snap(client, g, who):
    return client.get(f"/api/games/{g['code']}", headers=auth(g[who]["token"])).json()


def test_players_cannot_see_other_players_money_or_logs(client, game):
    code = game["code"]
    pay(
        client, game, "Ana", "Ben", 120, key="p1"
    )  # Hana (host) and Cara-like third party: none; Ben, Ana involved
    host = auth(game["host"]["token"])
    client.post(
        f"/api/games/{code}/bank/pay",
        headers=host,
        json={"player_id": game["Ben"]["player_id"], "amount": 30},
    )

    # A third player who is not involved in any of it.
    cam = client.post(f"/api/games/{code}/join", json={"name": "Cam"}).json()
    game["Cam"] = cam
    cam_view = raw_snap(client, game, "Cam")

    # Cam sees names (no money) for everyone but himself.
    by_name = {p["name"]: p["balance"] for p in cam_view["players"]}
    assert by_name["Cam"] == 1000
    assert by_name["Ana"] is None and by_name["Ben"] is None and by_name["Hana"] is None
    # No ledger and no payment activity: only public events (joins).
    assert cam_view["transactions"] == []
    assert all(a["type"] in ("player_joined", "game_ended", "turn_passed") for a in cam_view["activity"])
    assert "paid" not in " ".join(a["text"] for a in cam_view["activity"])

    # Ana and Ben see their own money and their own transactions only.
    ana_view = raw_snap(client, game, "Ana")
    assert {p["name"]: p["balance"] for p in ana_view["players"]} == {
        "Hana": None,
        "Ana": 880,
        "Ben": None,
        "Cam": None,
    }
    assert [t["amount"] for t in ana_view["transactions"]] == [120]
    ben_view = raw_snap(client, game, "Ben")
    assert sorted(t["amount"] for t in ben_view["transactions"]) == [30, 120]

    # The host (the bank) sees everything.
    host_view = raw_snap(client, game, "host")
    assert all(p["balance"] is not None for p in host_view["players"])
    assert len(host_view["transactions"]) == 2
    assert any("Ana paid Ben" in a["text"] for a in host_view["activity"])


def test_balances_are_revealed_to_everyone_when_the_game_ends(client, game):
    pay(client, game, "Ana", "Ben", 100, key="p1")
    client.post(f"/api/games/{game['code']}/end", headers=auth(game["host"]["token"]))
    view = raw_snap(client, game, "Ben")
    assert {p["name"]: p["balance"] for p in view["players"]} == {"Hana": 1000, "Ana": 900, "Ben": 1100}
    # the ledger itself stays private
    assert [t["amount"] for t in view["transactions"]] == [100]


def test_live_events_only_reach_the_people_involved_and_the_host(client, game):
    code = game["code"]

    def drain(ws):
        ws.receive_json()  # presence
        return ws.receive_json()["seq"]  # hello

    with (
        client.websocket_connect(f"/api/games/{code}/ws?token={game['Ana']['token']}") as ana_ws,
        client.websocket_connect(f"/api/games/{code}/ws?token={game['Ben']['token']}") as ben_ws,
        client.websocket_connect(f"/api/games/{code}/ws?token={game['host']['token']}") as host_ws,
    ):
        drain(ana_ws)
        ana_ws.receive_json()  # presence from Ben joining the socket
        ana_ws.receive_json()  # presence from host joining the socket
        drain(ben_ws)
        ben_ws.receive_json()  # presence from host joining the socket
        drain(host_ws)

        # A third, uninvolved player connects too.
        cam = client.post(f"/api/games/{code}/join", json={"name": "Cam"}).json()
        with client.websocket_connect(f"/api/games/{code}/ws?token={cam['token']}") as cam_ws:
            # (join broadcast and presence frames are public; skip until the hello frame)
            while cam_ws.receive_json()["kind"] != "hello":
                pass
            pay(client, game, "Ana", "Ben", 40, key="live1")
            # Ana and Ben (and the host) receive the payment event, with its text.
            for ws in (ana_ws, ben_ws, host_ws):
                msg = ws.receive_json()
                while msg["kind"] != "event" or msg["type"] != "transaction":
                    msg = ws.receive_json()
                assert "Ana paid Ben" in msg["text"] and "involves" not in msg
            # Cam gets nothing about the payment: the next frame is a later, unrelated one (here: none).
            client.post(f"/api/games/{code}/join", json={"name": "Dee"})
            nxt = cam_ws.receive_json()
            while nxt["kind"] == "presence":
                nxt = cam_ws.receive_json()
            assert nxt["type"] == "player_joined"  # public event arrived; the payment did not


def test_live_transaction_events_carry_flow_data_for_the_dashboard(client, game):
    code = game["code"]
    with client.websocket_connect(f"/api/games/{code}/ws?token={game['host']['token']}") as ws:
        while ws.receive_json()["kind"] != "hello":
            pass
        pay(client, game, "Ana", "Ben", 25, key="f1")
        msg = ws.receive_json()
        while msg["kind"] != "event":
            msg = ws.receive_json()
        assert msg["data"] == {
            "from_id": game["Ana"]["player_id"],
            "to_id": game["Ben"]["player_id"],
            "amount": 25,
            "kind": "payment",
        }
        assert "involves" not in msg
    # the stored activity feed does not carry flow data
    assert all("data" not in a for a in raw_snap(client, game, "host")["activity"])


def test_modes_list_and_defaults(client):
    data = client.get("/api/modes").json()
    assert data["default"] == "monopoly"
    ids = [m["id"] for m in data["modes"]]
    assert ids[0] == "monopoly" and "custom" in ids
    mono = data["modes"][0]
    assert mono["starting_balance"] == 1500
    assert {a["id"] for a in mono["bank_actions"]} >= {"go", "income_tax", "luxury_tax", "jail"}


def test_new_games_default_to_monopoly(client):
    r = client.post("/api/games", json={"host_name": "Hana"}).json()
    s = client.get(f"/api/games/{r['code']}", headers=auth(r["token"])).json()
    assert s["game"]["mode"]["id"] == "monopoly"
    assert s["game"]["starting_balance"] == 1500 and s["game"]["currency"] == "$"
    assert s["players"][0]["balance"] == 1500


def test_house_rules_override_the_mode_defaults(client):
    r = client.post(
        "/api/games",
        json={"host_name": "Hana", "mode": "monopoly", "starting_balance": 2000, "currency": "₹"},
    ).json()
    s = client.get(f"/api/games/{r['code']}", headers=auth(r["token"])).json()
    assert s["game"]["starting_balance"] == 2000 and s["game"]["currency"] == "₹"
    assert s["game"]["mode"]["id"] == "monopoly"


def test_custom_mode_and_unknown_mode(client):
    r = client.post("/api/games", json={"host_name": "Hana", "mode": "custom"}).json()
    s = client.get(f"/api/games/{r['code']}", headers=auth(r["token"])).json()
    assert s["game"]["mode"]["id"] == "custom" and s["game"]["starting_balance"] == 1000
    assert s["game"]["mode"]["bank_actions"] == []
    bad = client.post("/api/games", json={"host_name": "Hana", "mode": "chess"})
    assert bad.status_code == 400 and bad.json()["code"] == "unknown_mode"


def test_mode_bank_actions_work_through_the_normal_bank_endpoints(client):
    """'Pass GO' is a 200 bank payment with a note; no special server endpoint is needed."""
    r = client.post("/api/games", json={"host_name": "Hana", "host_plays": False}).json()
    ana = client.post(f"/api/games/{r['code']}/join", json={"name": "Ana"}).json()
    go = next(a for a in client.get("/api/modes").json()["modes"][0]["bank_actions"] if a["id"] == "go")
    ok = client.post(
        f"/api/games/{r['code']}/bank/pay",
        headers=auth(r["token"]),
        json={"player_id": ana["player_id"], "amount": go["amount"], "note": go["label"]},
    )
    assert ok.status_code == 200 and ok.json()["result"]["note"] == "Pass GO"
    s = client.get(f"/api/games/{r['code']}", headers=auth(ana["token"])).json()
    assert next(p for p in s["players"] if p["name"] == "Ana")["balance"] == 1700


def test_host_can_switch_the_game_mode(client, game):
    code = game["code"]
    host, ana = auth(game["host"]["token"]), auth(game["Ana"]["token"])
    assert snap(client, game)["game"]["mode"]["id"] == "monopoly"  # the default for new games
    assert client.post(f"/api/games/{code}/mode", headers=ana, json={"mode": "custom"}).status_code == 403
    assert client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "chess"}).status_code == 400
    before = balances(client, game)
    ok = client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "custom"})
    assert ok.status_code == 200 and ok.json()["result"]["mode"]["id"] == "custom"
    s = snap(client, game)
    assert s["game"]["mode"]["id"] == "custom" and s["game"]["mode"]["bank_actions"] == []
    assert balances(client, game) == before  # balances never change with the mode
    # players see the change in their own snapshot too
    assert raw_snap(client, game, "Ana")["game"]["mode"]["id"] == "custom"
    assert client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "monopoly"}).status_code == 200


def test_host_sets_the_player_sequence(client, game):
    code = game["code"]
    host, ana = auth(game["host"]["token"]), auth(game["Ana"]["token"])
    ids = {n: game[n]["player_id"] for n in ("Ana", "Ben")}
    ids["Hana"] = game["host"]["player_id"]

    def names(who):
        return [p["name"] for p in raw_snap(client, game, who)["players"]]

    assert names("host") == ["Hana", "Ana", "Ben"]  # join order by default
    url = f"/api/games/{code}/players/order"
    assert client.post(url, headers=ana, json={"order": [ids["Ben"], ids["Ana"]]}).status_code == 403
    assert client.post(url, headers=host, json={"order": [ids["Ben"], ids["Ben"]]}).status_code == 400
    assert client.post(url, headers=host, json={"order": [9999]}).status_code == 404
    assert client.post(url, headers=host, json={"order": []}).status_code == 422

    ok = client.post(url, headers=host, json={"order": [ids["Ben"], ids["Hana"], ids["Ana"]]})
    assert ok.status_code == 200
    assert names("host") == ["Ben", "Hana", "Ana"]
    assert names("Ana") == ["Ben", "Hana", "Ana"]  # players see the same sequence

    # a subset swaps only those players' places; a later joiner goes to the end
    assert client.post(url, headers=host, json={"order": [ids["Ana"], ids["Ben"]]}).status_code == 200
    assert names("host") == ["Ana", "Hana", "Ben"]
    client.post(f"/api/games/{code}/join", json={"name": "Cam"})
    assert names("host") == ["Ana", "Hana", "Ben", "Cam"]


def test_host_changes_a_players_colour(client, game):
    code = game["code"]
    host, ana = auth(game["host"]["token"]), auth(game["Ana"]["token"])
    url = f"/api/games/{code}/players/{game['Ben']['player_id']}/colour"
    assert client.post(url, headers=ana, json={"colour": "#112233"}).status_code == 403
    assert client.post(url, headers=host, json={"colour": "red"}).status_code == 400
    assert client.post(url, headers=host, json={"colour": "#ABCDEF"}).status_code == 200
    ben = next(p for p in raw_snap(client, game, "Ana")["players"] if p["name"] == "Ben")
    assert ben["colour"] == "#abcdef"
    missing = client.post(f"/api/games/{code}/players/9999/colour", headers=host, json={"colour": "#112233"})
    assert missing.status_code == 404


def test_monopoly_is_the_default_mode(client):
    assert client.get("/api/modes").json()["default"] == "monopoly"
    r = client.post("/api/games", json={"host_name": "Hana"}).json()
    snap_ = client.get(f"/api/games/{r['code']}", headers=auth(r["token"])).json()
    assert snap_["game"]["mode"]["id"] == "monopoly"


def _status_url(game, who, suffix=""):
    return f"/api/games/{game['code']}/players/{game[who]['player_id']}/status{suffix}"


def test_jail_costs_three_turns_unless_the_fine_is_paid(client, game):
    host, ana, ben = (auth(game[w]["token"]) for w in ("host", "Ana", "Ben"))
    # only the host sends players to jail; modes without the effect refuse it
    assert client.post(_status_url(game, "Ana"), headers=ana, json={"effect": "jail"}).status_code == 403
    assert client.post(_status_url(game, "Ana"), headers=host, json={"effect": "dungeon"}).status_code == 400
    ok = client.post(_status_url(game, "Ana"), headers=host, json={"effect": "jail"})
    assert ok.status_code == 200 and ok.json()["result"]["turns_left"] == 3
    assert client.post(_status_url(game, "Ana"), headers=host, json={"effect": "jail"}).status_code == 409

    # everybody can see who is in jail; money stays private
    for who in ("host", "Ana", "Ben"):
        players = {p["name"]: p for p in raw_snap(client, game, who)["players"]}
        assert players["Ana"]["statuses"] == [
            {"effect": "jail", "label": "Jail", "turns_left": 3, "decided": False}
        ]
        assert players["Ben"]["statuses"] == []

    # miss three turns: the third releases
    for left in (2, 1, 0):
        r = client.post(_status_url(game, "Ana", "/jail/turn"), headers=host)
        assert r.status_code == 200 and r.json()["result"]["turns_left"] == left
    assert raw_snap(client, game, "Ana")["players"][1]["statuses"] == []
    assert client.post(_status_url(game, "Ana", "/jail/turn"), headers=host).status_code == 404
    assert balances(client, game)["Ana"] == 1000  # missing turns costs no money


def test_paying_the_jail_fine_clears_the_status(client, game):
    host, ana, ben = (auth(game[w]["token"]) for w in ("host", "Ana", "Ben"))
    client.post(_status_url(game, "Ana"), headers=host, json={"effect": "jail"})
    # another player cannot pay it for them; the player and the host can
    assert client.post(_status_url(game, "Ana", "/jail/pay"), headers=ben).status_code == 403
    paid = client.post(_status_url(game, "Ana", "/jail/pay"), headers=ana)
    assert paid.status_code == 200 and paid.json()["result"]["kind"] == "bank_collect"
    assert balances(client, game)["Ana"] == 950
    ana_view = raw_snap(client, game, "Ana")
    assert ana_view["players"][1]["statuses"] == []
    assert any(t["note"] == "Jail fine" and t["amount"] == 50 for t in ana_view["transactions"])
    # nothing to pay any more
    assert client.post(_status_url(game, "Ana", "/jail/pay"), headers=ana).status_code == 404

    # the host can pay for a player; a player short of money cannot be fined into negative
    client.post(_status_url(game, "Ben"), headers=host, json={"effect": "jail"})
    client.post(
        f"/api/games/{game['code']}/bank/collect",
        headers=host,
        json={"player_id": game["Ben"]["player_id"], "amount": 980},
    )
    short = client.post(_status_url(game, "Ben", "/jail/pay"), headers=ben)
    assert short.status_code == 409 and short.json()["code"] == "insufficient"
    assert balances(client, game)["Ben"] == 20
    assert client.post(_status_url(game, "Ben", "/jail/clear"), headers=host).status_code == 200
    assert raw_snap(client, game, "Ben")["players"][2]["statuses"] == []


def test_status_effects_follow_the_game_mode(client):
    custom = client.post("/api/games", json={"host_name": "Hana", "mode": "custom"}).json()
    ana = client.post(f"/api/games/{custom['code']}/join", json={"name": "Ana"}).json()
    r = client.post(
        f"/api/games/{custom['code']}/players/{ana['player_id']}/status",
        headers=auth(custom["token"]),
        json={"effect": "jail"},
    )
    assert r.status_code == 400 and r.json()["code"] == "not_in_mode"
    modes = {m["id"]: m for m in client.get("/api/modes").json()["modes"]}
    assert [e["id"] for e in modes["monopoly"]["status_effects"]] == ["jail", "dice"]
    jail_def = modes["monopoly"]["status_effects"][0]
    assert jail_def["turns"] == 3 and jail_def["fine"] == 50 and jail_def["kind"] == "penalty"
    assert modes["custom"]["status_effects"] == []


# ---------------------------------------------------------------- dice
def _dice(client, game, who="host"):
    return raw_snap(client, game, who)["game"]["turn"]


def _post(client, game, who, path, **json):
    return client.post(
        f"/api/games/{game['code']}{path}", headers=auth(game[who]["token"]), json=json or None
    )


def _rig(monkeypatch, *values):
    rolls = iter(values)
    monkeypatch.setattr("app.domain.turns.roll_die", lambda: next(rolls))


def test_dice_start_with_the_first_player_and_pass_round_in_sequence(client, game, monkeypatch):
    # sequence is Hana (host, plays), Ana, Ben
    assert _dice(client, game)["holder_id"] == game["host"]["player_id"]
    _rig(monkeypatch, 3, 4)
    assert _post(client, game, "Ana", "/turn/roll").status_code == 403  # not Ana's turn
    r = _post(client, game, "host", "/turn/roll")
    assert r.status_code == 200 and r.json()["result"]["total"] == 7
    last = _dice(client, game, "Ben")["last"]  # everyone sees the roll
    assert (last["d1"], last["d2"], last["double"]) == (3, 4, False)
    assert _post(client, game, "host", "/turn/roll").status_code == 409  # one roll, then end the turn
    assert _post(client, game, "Ana", "/turn/end").status_code == 403
    assert _post(client, game, "host", "/turn/end").status_code == 200
    assert _dice(client, game)["holder_id"] == game["Ana"]["player_id"]
    assert _post(client, game, "Ana", "/turn/end").status_code == 409  # must roll before ending
    _rig(monkeypatch, 1, 2)
    _post(client, game, "Ana", "/turn/roll")
    _post(client, game, "Ana", "/turn/end")
    assert _dice(client, game)["holder_id"] == game["Ben"]["player_id"]
    _rig(monkeypatch, 6, 5)
    _post(client, game, "Ben", "/turn/roll")
    _post(client, game, "Ben", "/turn/end")
    assert _dice(client, game)["holder_id"] == game["host"]["player_id"]  # all the way round


def test_doubles_roll_again_and_the_third_double_goes_to_jail(client, game, monkeypatch):
    _rig(monkeypatch, 2, 2, 5, 5, 6, 6)
    for expected_streak in (1, 2):
        r = _post(client, game, "host", "/turn/roll").json()["result"]
        assert r["double"] is True and r["streak"] == expected_streak
        assert _dice(client, game)["holder_id"] == game["host"]["player_id"]  # still their turn
    third = _post(client, game, "host", "/turn/roll").json()["result"]
    assert third["jailed"] is True
    me = {p["name"]: p for p in raw_snap(client, game, "Ana")["players"]}["Hana"]
    assert [s["effect"] for s in me["statuses"]] == ["jail"]
    assert _dice(client, game)["holder_id"] == game["Ana"]["player_id"]  # the turn moved on


def test_jailed_player_gets_one_chance_to_pay_then_misses_three_turns(client, game, monkeypatch):
    """First turn in Jail: pay the fine and play, or miss this turn (and the next two) with no more chance."""
    host = auth(game["host"]["token"])
    ids = {n: game[n]["player_id"] for n in ("Ana", "Ben")}
    ana_url = f"/players/{ids['Ana']}/status/jail"
    _rig(monkeypatch, *([1, 2] * 20))  # plenty of non-double rolls
    client.post(_status_url(game, "Ana"), headers=host, json={"effect": "jail"})
    _post(client, game, "host", "/turn/end")  # host (holder) ends turn: dice reaches Ana, who is in Jail
    assert _dice(client, game)["holder_id"] == ids["Ana"]
    blocked = _post(client, game, "Ana", "/turn/roll")
    assert blocked.status_code == 409 and blocked.json()["code"] == "in_jail"  # must decide first

    # Ana chooses to miss: her one chance to pay is gone; the dice moves on
    assert _post(client, game, "Ana", f"{ana_url}/turn").status_code == 200

    def ana_status():
        return {p["name"]: p for p in raw_snap(client, game, "Ana")["players"]}["Ana"]["statuses"]

    assert ana_status() == [{"effect": "jail", "label": "Jail", "turns_left": 2, "decided": True}]
    late = _post(client, game, "Ana", f"{ana_url}/pay")
    assert late.status_code == 409 and late.json()["code"] == "chance_used"
    assert balances(client, game)["Ana"] == 1000
    assert _dice(client, game)["holder_id"] == ids["Ben"]

    def lap():  # Ben and the host take their turns; Ana is skipped
        for who in ("Ben", "host"):
            _post(client, game, who, "/turn/roll")
            _post(client, game, who, "/turn/end")

    lap()  # Ana skipped (second missed turn): 1 left
    assert _dice(client, game)["holder_id"] == ids["Ben"]
    assert ana_status()[0]["turns_left"] == 1
    lap()  # Ana skipped (third missed turn): released
    assert ana_status() == []
    lap()  # the dice finally reaches Ana again
    assert _dice(client, game)["holder_id"] == ids["Ana"]
    assert _post(client, game, "Ana", "/turn/roll").status_code == 200


def test_jailed_player_who_pays_the_fine_plays_the_turn(client, game, monkeypatch):
    host = auth(game["host"]["token"])
    ana_id = game["Ana"]["player_id"]
    client.post(_status_url(game, "Ana"), headers=host, json={"effect": "jail"})
    _post(client, game, "host", "/turn/end")
    assert _dice(client, game)["holder_id"] == ana_id
    paid = _post(client, game, "Ana", f"/players/{ana_id}/status/jail/pay")
    assert paid.status_code == 200 and balances(client, game)["Ana"] == 950
    _rig(monkeypatch, 2, 5)
    assert _post(client, game, "Ana", "/turn/roll").status_code == 200  # free to roll now


def test_host_can_override_the_dice(client, game, monkeypatch):
    ids = {n: game[n]["player_id"] for n in ("Ana", "Ben")}
    assert _post(client, game, "Ana", "/turn/assign", player_id=ids["Ben"]).status_code == 403
    assert _post(client, game, "host", "/turn/assign", player_id=ids["Ben"]).status_code == 200
    assert _dice(client, game)["holder_id"] == ids["Ben"]
    assert _post(client, game, "Ana", "/turn/pass").status_code == 403
    assert _post(client, game, "host", "/turn/pass").status_code == 200  # Ben -> Hana (next in sequence)
    assert _dice(client, game)["holder_id"] == game["host"]["player_id"]
    _rig(monkeypatch, 4, 1)
    assert _post(client, game, "host", "/turn/roll").status_code == 200  # the host (holder) rolls
    # the host can also roll on behalf of the current holder
    _post(client, game, "host", "/turn/assign", player_id=ids["Ana"])
    _rig(monkeypatch, 6, 3)
    assert _post(client, game, "host", "/turn/roll").json()["result"]["roller_id"] == ids["Ana"]
    # taking the dice away from a jailed player counts as their missed turn
    client.post(_status_url(game, "Ben"), headers=auth(game["host"]["token"]), json={"effect": "jail"})
    _post(client, game, "host", "/turn/assign", player_id=ids["Ben"])
    _post(client, game, "host", "/turn/pass")
    ben = {p["name"]: p for p in raw_snap(client, game, "Ben")["players"]}["Ben"]
    assert ben["statuses"] == [{"effect": "jail", "label": "Jail", "turns_left": 2, "decided": True}]


def test_dice_follow_the_game_mode(client, game):
    code = game["code"]
    host = auth(game["host"]["token"])
    assert _dice(client, game) is not None
    client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "custom"})
    assert _dice(client, game) is None
    assert _post(client, game, "host", "/turn/roll").status_code == 400
    client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "monopoly"})
    assert _dice(client, game)["holder_id"] == game["host"]["player_id"]
    # the generic status endpoints refuse the dice
    r = client.post(_status_url(game, "Ana"), headers=host, json={"effect": "dice"})
    assert r.status_code == 400 and r.json()["code"] == "not_a_penalty"


def test_the_holder_can_end_the_turn_after_any_completed_roll(client, game, monkeypatch):
    """After a roll the holder may end their turn; with doubles they can also choose to roll again."""
    host_id, ana_id = game["host"]["player_id"], game["Ana"]["player_id"]
    assert _post(client, game, "host", "/turn/end").status_code == 200  # host may always pass
    assert _dice(client, game)["holder_id"] == ana_id and _dice(client, game)["acted"] is False
    assert _post(client, game, "Ana", "/turn/end").status_code == 409  # nothing rolled yet
    _rig(monkeypatch, 3, 3)  # doubles
    _post(client, game, "Ana", "/turn/roll")
    state = _dice(client, game)
    assert state["acted"] is True and state["rolled"] is False and state["streak"] == 1
    assert _post(client, game, "Ana", "/turn/end").status_code == 200  # may end instead of rolling again
    after = _dice(client, game)
    assert after["holder_id"] != ana_id and after["acted"] is False and after["streak"] == 0
    assert host_id != ana_id


# ---------------------------------------------------------------- UnoPoly (cards instead of dice)
import pytest  # noqa: E402


@pytest.fixture()
def uno(client):
    """An UnoPoly game: Hana (host, plays), Ana, Ben, Cam in that sequence."""
    host = client.post("/api/games", json={"host_name": "Hana", "mode": "unopoly"}).json()
    g = {"code": host["code"], "host": host}
    for name in ("Ana", "Ben", "Cam"):
        g[name] = client.post(f"/api/games/{g['code']}/join", json={"name": name}).json()
    return g


def _holder_name(client, g):
    snap_ = raw_snap(client, g, "host")
    turn = snap_["game"]["turn"]
    return next(p["name"] for p in snap_["players"] if p["id"] == turn["holder_id"])


def _status_names(client, g, name, who="host"):
    me = {p["name"]: p for p in raw_snap(client, g, who)["players"]}[name]
    return [s["effect"] for s in me["statuses"]]


def test_unopoly_derives_from_monopoly(client):
    from app.domain.modes import MODES, MonopolyGameMode, UnoPolyGameMode

    assert issubclass(UnoPolyGameMode, MonopolyGameMode)
    mono, unop = MODES["monopoly"], MODES["unopoly"]
    # same money, same shortcuts and fines; only the turn mechanic differs
    assert (unop.starting_balance, unop.quick_amounts, unop.bank_actions) == (
        mono.starting_balance,
        mono.quick_amounts,
        mono.bank_actions,
    )
    assert (mono.turn_effect, mono.callouts) == ("dice", False)
    assert (unop.turn_effect, unop.callouts) == ("card", True)
    listed = {m["id"]: m for m in client.get("/api/modes").json()["modes"]}
    assert list(listed) == ["monopoly", "unopoly", "custom"]
    assert [e["id"] for e in listed["unopoly"]["status_effects"]] == ["jail", "card"]


def test_unopoly_has_no_dice_but_the_holder_can_end_the_turn_any_time(client, uno):
    turn = raw_snap(client, uno, "Ana")["game"]["turn"]
    assert turn["effect"] == "card" and turn["label"] == "Card"
    assert _holder_name(client, uno) == "Hana"
    assert _post(client, uno, "host", "/turn/roll").status_code == 400  # no dice here
    assert _post(client, uno, "Ana", "/turn/end").status_code == 403  # not Ana's turn
    for expected in ("Ana", "Ben", "Cam", "Hana"):  # no roll needed; round in sequence
        holder = _holder_name(client, uno)
        assert _post(client, uno, "host" if holder == "Hana" else holder, "/turn/end").status_code == 200
        assert _holder_name(client, uno) == expected
    assert _status_names(client, uno, "Hana") == ["card"]


def test_skip_passes_over_the_next_player(client, uno):
    assert _post(client, uno, "Ana", "/turn/skip").status_code == 403
    assert _post(client, uno, "host", "/turn/skip").status_code == 200
    assert _holder_name(client, uno) == "Ben"  # Ana was skipped
    texts = [a["text"] for a in raw_snap(client, uno, "host")["activity"]]
    assert "Ana was skipped" in texts and "Hana played Skip" in texts


def test_reverse_flips_the_direction_of_play(client, uno):
    assert _post(client, uno, "host", "/turn/reverse").status_code == 200
    assert raw_snap(client, uno, "Ana")["game"]["turn"]["direction"] == -1
    assert _holder_name(client, uno) == "Cam"  # the way we came
    _post(client, uno, "Cam", "/turn/end")
    assert _holder_name(client, uno) == "Ben"  # and it keeps going that way
    _post(client, uno, "Ben", "/turn/reverse")
    assert raw_snap(client, uno, "Ana")["game"]["turn"]["direction"] == 1
    assert _holder_name(client, uno) == "Cam"


def test_skip_reverse_and_callouts_only_exist_in_unopoly(client, game):
    for path in ("/turn/skip", "/turn/reverse"):
        assert _post(client, game, "host", path).status_code == 400
    assert _post(client, game, "Ana", "/turn/callout").status_code == 400


def test_jail_still_applies_to_the_card_turn(client, uno):
    host = auth(uno["host"]["token"])
    ana_url = f"/api/games/{uno['code']}/players/{uno['Ana']['player_id']}/status"
    client.post(ana_url, headers=host, json={"effect": "jail"})
    _post(client, uno, "host", "/turn/end")  # the card reaches Ana, in Jail for the first time
    assert _holder_name(client, uno) == "Ana"
    assert _post(client, uno, "Ana", "/turn/end").status_code == 200  # ending the turn = missing it
    ana = {p["name"]: p for p in raw_snap(client, uno, "Ana")["players"]}["Ana"]
    assert ana["statuses"][0]["effect"] == "jail" and ana["statuses"][0]["decided"] is True
    _post(client, uno, "Ben", "/turn/end")
    _post(client, uno, "Cam", "/turn/end")
    _post(client, uno, "host", "/turn/end")  # Ana is skipped and counts down
    assert _holder_name(client, uno) == "Ben"


def test_call_out_needs_everyone_to_agree_and_then_sends_the_player_to_jail(client, uno):
    assert _post(client, uno, "Ben", "/turn/callout").status_code == 409  # nobody has ended a turn yet
    _post(client, uno, "host", "/turn/end")  # Hana ends her turn: the card is with Ana
    assert _post(client, uno, "host", "/turn/callout").status_code == 403  # cannot call yourself out
    started = _post(client, uno, "Ben", "/turn/callout")
    assert started.status_code == 200
    callout = raw_snap(client, uno, "Cam")["game"]["turn"]["callout"]
    assert (
        callout["target_id"] == uno["host"]["player_id"] and callout["caller_id"] == uno["Ben"]["player_id"]
    )
    assert sorted(callout["voters"]) == sorted(uno[n]["player_id"] for n in ("Ana", "Ben", "Cam"))
    assert callout["agree"] == [uno["Ben"]["player_id"]]  # the caller agrees
    assert _post(client, uno, "Cam", "/turn/callout").status_code == 409  # one at a time
    assert (
        _post(client, uno, "host", "/turn/callout/vote", agree=True).status_code == 403
    )  # the target can't vote
    assert _post(client, uno, "Ana", "/turn/callout/vote", agree=True).status_code == 200
    assert _post(client, uno, "Ana", "/turn/callout/vote", agree=True).status_code == 409  # already voted
    assert "jail" not in _status_names(client, uno, "Hana")  # still waiting for Cam
    assert _post(client, uno, "Cam", "/turn/callout/vote", agree=True).status_code == 200
    assert "jail" in _status_names(client, uno, "Hana")  # unanimous: Hana goes to Jail
    assert raw_snap(client, uno, "Ana")["game"]["turn"]["callout"] is None


def test_one_disagreement_defeats_a_call_out(client, uno):
    _post(client, uno, "host", "/turn/end")
    _post(client, uno, "Ben", "/turn/callout")
    assert _post(client, uno, "Cam", "/turn/callout/vote", agree=False).status_code == 200
    assert "jail" not in _status_names(client, uno, "Hana")
    assert raw_snap(client, uno, "Ana")["game"]["turn"]["callout"] is None
    texts = [a["text"] for a in raw_snap(client, uno, "host")["activity"]]
    assert any("failed: Cam disagreed" in t for t in texts)


def test_a_call_out_lapses_when_the_next_turn_ends_and_the_host_can_cancel_one(client, uno):
    _post(client, uno, "host", "/turn/end")
    _post(client, uno, "Ben", "/turn/callout")
    assert _post(client, uno, "Ben", "/turn/callout/cancel").status_code == 403  # host only
    assert _post(client, uno, "host", "/turn/callout/cancel").status_code == 200
    assert raw_snap(client, uno, "Ana")["game"]["turn"]["callout"] is None
    _post(client, uno, "Ben", "/turn/callout")
    _post(client, uno, "Ana", "/turn/end")  # Ana (holder) ends her turn: the old call-out lapses
    turn = raw_snap(client, uno, "Ana")["game"]["turn"]
    assert turn["callout"] is None and turn["last_ender"] == uno["Ana"]["player_id"]
    assert _post(client, uno, "Ana", "/turn/callout").status_code == 403  # Ana cannot call out herself


def test_switching_between_monopoly_and_unopoly_carries_the_turn_over(client, uno):
    code, host = uno["code"], auth(uno["host"]["token"])
    _post(client, uno, "host", "/turn/reverse")  # direction -1, card with Cam
    assert client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "monopoly"}).status_code == 200
    turn = raw_snap(client, uno, "host")["game"]["turn"]
    assert turn["effect"] == "dice" and turn["direction"] == 1  # direction resets
    assert _holder_name(client, uno) == "Cam"  # same person is still up
    assert _status_names(client, uno, "Cam") == ["dice"]
    client.post(f"/api/games/{code}/mode", headers=host, json={"mode": "unopoly"})
    assert _status_names(client, uno, "Cam") == ["card"]


# ---------------------------------------------------------------- restart
def test_restart_resets_the_game_but_keeps_the_players(client, uno):
    code, host = uno["code"], auth(uno["host"]["token"])
    ana, ben = auth(uno["Ana"]["token"]), auth(uno["Ben"]["token"])
    colour = {p["name"]: p["colour"] for p in raw_snap(client, uno, "host")["players"]}
    client.post(
        f"/api/games/{code}/transactions", headers=ana, json={"to_id": uno["Ben"]["player_id"], "amount": 300}
    )
    client.post(f"/api/games/{code}/requests", headers=ben, json={"amount": 50})
    client.post(
        f"/api/games/{code}/players/{uno['Cam']['player_id']}/status", headers=host, json={"effect": "jail"}
    )
    _post(client, uno, "host", "/turn/reverse")
    client.post(f"/api/games/{code}/end", headers=host)  # even a finished game can be restarted

    assert client.post(f"/api/games/{code}/restart", headers=ana).status_code == 403  # host only
    assert client.post(f"/api/games/{code}/restart", headers=host).status_code == 200

    view = raw_snap(client, uno, "host")
    assert view["game"]["status"] == "active"
    assert {p["name"]: p["balance"] for p in view["players"]} == {
        "Hana": 1500,
        "Ana": 1500,
        "Ben": 1500,
        "Cam": 1500,
    }
    assert view["transactions"] == [] and view["requests"] == []
    assert {p["name"]: p["colour"] for p in view["players"]} == colour  # names, colours, order kept
    assert [p["name"] for p in view["players"]] == ["Hana", "Ana", "Ben", "Cam"]
    assert [s["effect"] for p in view["players"] for s in p["statuses"]] == [
        "card"
    ]  # Jail gone; the card restarts
    assert (
        view["game"]["turn"]["holder_id"] == uno["host"]["player_id"]
        and view["game"]["turn"]["direction"] == 1
    )
    assert [a["type"] for a in view["activity"]] == ["turn_passed", "game_restarted"]  # a clean activity feed
    # and play carries on
    assert _post(client, uno, "host", "/turn/end").status_code == 200


def test_host_settings_reach_every_device_and_survive_a_restart(client, game):
    code, host, ana = game["code"], auth(game["host"]["token"]), auth(game["Ana"]["token"])
    url = f"/api/games/{code}/settings"
    assert raw_snap(client, game, "Ana")["game"]["settings"] == {"siren_volume": 40}  # a quiet default
    assert client.post(url, headers=ana, json={"siren_volume": 10}).status_code == 403  # host only
    for bad in (-1, 101, 5.5, "loud", True):
        assert client.post(url, headers=host, json={"siren_volume": bad}).status_code == 422, bad
    ok = client.post(url, headers=host, json={"siren_volume": 15})
    assert ok.status_code == 200 and ok.json()["result"] == {"siren_volume": 15}
    for who in ("host", "Ana", "Ben"):  # players get the same setting, so their phones play it at that volume
        assert raw_snap(client, game, who)["game"]["settings"]["siren_volume"] == 15
    assert client.post(url, headers=host, json={}).status_code == 200  # nothing to change is fine
    assert raw_snap(client, game, "Ana")["game"]["settings"]["siren_volume"] == 15
    client.post(f"/api/games/{code}/restart", headers=host)
    assert raw_snap(client, game, "Ana")["game"]["settings"]["siren_volume"] == 15
    assert client.post(url, headers=host, json={"siren_volume": 0}).status_code == 200  # silent is allowed


def test_host_can_test_the_siren_on_every_device(client, game):
    url = f"/api/games/{game['code']}/settings/test-siren"
    assert client.post(url, headers=auth(game["Ana"]["token"])).status_code == 403  # host only
    with client.websocket_connect(f"/api/games/{game['code']}/ws?token={game['Ben']['token']}") as ws:
        while ws.receive_json()["kind"] != "hello":
            pass
        assert client.post(url, headers=auth(game["host"]["token"])).status_code == 200
        msg = ws.receive_json()
        while msg["kind"] != "event":
            msg = ws.receive_json()
        assert msg["type"] == "siren_test"  # players' phones react to this by playing the siren
