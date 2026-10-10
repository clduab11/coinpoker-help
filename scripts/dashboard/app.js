(() => {
  "use strict";

  /* BEGIN BUNDLED REFERENCE */
  const LOCAL_REFERENCE = {
    "schema_version": 1,
    "title": "Poker Study Reference",
    "scope": "Offline educational reference for standard 52-card no-limit Texas Hold'em. Not live recommendations, perception validation, or advice activation.",
    "reviewed_utc": "2026-10-10T05:45:26Z",
    "sources": [
      {
        "id": "pokernews-hands",
        "title": "Poker Hand Rankings",
        "url": "https://www.pokernews.com/poker-hands/",
        "publisher": "PokerNews"
      },
      {
        "id": "pokernews-straight",
        "title": "What is a Straight in Poker? Definition & Examples",
        "url": "https://www.pokernews.com/poker-hands/straight.htm",
        "publisher": "PokerNews"
      },
      {
        "id": "pokernews-ties",
        "title": "Tied Poker Hands - Split Pots & Tie-Breaker Rules Explained",
        "url": "https://www.pokernews.com/poker-hands/tied-poker-hands.htm",
        "publisher": "PokerNews"
      },
      {
        "id": "upswing-pot-odds",
        "title": "Pot Odds Explained and How to Calculate Them",
        "url": "https://upswingpoker.com/pot-odds-step-by-step/",
        "publisher": "Upswing Poker"
      },
      {
        "id": "pokerology-outs",
        "title": "Poker Outs: How to Count Outs and Calculate Odds",
        "url": "https://www.pokerology.com/poker/math/drawing-odds/",
        "publisher": "Pokerology"
      },
      {
        "id": "upswing-six-max",
        "title": "The Ultimate Guide to 6-Handed Poker",
        "url": "https://upswingpoker.com/6-handed-max-poker-strategy/",
        "publisher": "Upswing Poker"
      },
      {
        "id": "gtowizard-large-opens",
        "title": "How To Respond to Large Preflop Raises in Poker",
        "url": "https://blog.gtowizard.com/how-to-respond-to-large-preflop-raises-in-poker/",
        "publisher": "GTO Wizard"
      },
      {
        "id": "upswing-bet-numbering",
        "title": "What is a 2-Bet in Poker?",
        "url": "https://upswingpoker.com/what-is-2-bet-poker/",
        "publisher": "Upswing Poker"
      },
      {
        "id": "upswing-three-bet",
        "title": "This Is Why (And How) You Need to 3-Bet More Often",
        "url": "https://upswingpoker.com/3-bet-strategy-aggressive-preflop/",
        "publisher": "Upswing Poker"
      },
      {
        "id": "upswing-aces",
        "title": "Do You Know How To Play Pocket Aces? Quiz Answers and Explanations",
        "url": "https://upswingpoker.com/pocket-aces-quiz-answers/",
        "publisher": "Upswing Poker"
      },
      {
        "id": "pokerstars-position",
        "title": "Position and Action Order",
        "url": "https://www.pokerstars.com/poker/learn/lesson/position/",
        "publisher": "PokerStars Learn"
      },
      {
        "id": "poker888-position-terms",
        "title": "Position: Terms and Lojack Alias",
        "url": "https://www.888poker.com/magazine/poker-terms/position",
        "publisher": "888poker"
      },
      {
        "id": "poker888-position-names",
        "title": "Poker Position Names",
        "url": "https://www.888poker.com/magazine/strategy/poker-position-names",
        "publisher": "888poker"
      },
      {
        "id": "pokernews-position",
        "title": "How to Learn Poker: Position Groups",
        "url": "https://www.pokernews.com/strategy/wpt-global-how-to-learn-poker-from-scratch-43778.htm",
        "publisher": "PokerNews"
      },
      {
        "id": "tda-2026",
        "title": "Poker TDA Rules 2026 v1.0: Button and Heads-Up",
        "url": "https://www.pokertda.com/view-poker-tda-rules/",
        "publisher": "Poker TDA (tournament rules, not client policy)"
      },
      {
        "id": "roberts-button",
        "title": "Robert's Rules of Poker v11: Button and Blinds",
        "url": "https://homepokertourney.org/roberts-rules-of-poker.htm",
        "publisher": "Home Poker Tourney (third-party reproduction)"
      }
    ],
    "sections": [
      {
        "id": "hand-rankings",
        "title": "Hand Rankings and Ties",
        "scope": "Standard high-hand Hold'em; best five cards, not starting-hand strength.",
        "paragraphs": [
          "At showdown, compare the best five-card hand available from seven cards. Hold'em permits zero, one, or two hole cards. First compare the hand category, then the ranks that define it; never use a sixth or seventh card to break a tie."
        ],
        "bullets": [
          "An ace is high except in A-2-3-4-5, a five-high straight (the wheel). T-J-Q-K-A is ace-high. Q-K-A-2-3 does not wrap into a straight. The same ace-low rule applies to straight flushes.",
          "Kickers count only within the best five cards. With the same pair, compare the three remaining cards from highest to lowest; stop at the first difference.",
          "Suits do not rank above one another. Identical best five-card ranks split the eligible pot, including when the board plays for everyone; house rules allocate any odd chip."
        ],
        "tables": [
          {
            "caption": "Strongest to weakest; a royal flush is the highest straight flush",
            "columns": ["Order", "Hand", "Definition and comparison"],
            "rows": [
              [1, "Royal flush", "A-K-Q-J-T of one suit; tied royals share the pot."],
              [2, "Straight flush", "Five sequential ranks of one suit; compare the top rank."],
              [3, "Four of a kind", "Four equal ranks; compare quads, then the remaining kicker."],
              [4, "Full house", "Three equal ranks plus a pair; compare trips first, then the pair."],
              [5, "Flush", "Five of one suit; compare all five ranks from highest to lowest."],
              [6, "Straight", "Five sequential ranks; compare only the top rank (wheel = five)."],
              [7, "Three of a kind", "Three equal ranks; compare trips, then the two kickers in order."],
              [8, "Two pair", "Compare the higher pair, then the lower pair, then the kicker."],
              [9, "One pair", "Compare the pair, then the three kickers in order."],
              [10, "High card", "No higher category; compare all five ranks in descending order."]
            ]
          }
        ],
        "source_ids": ["pokernews-hands", "pokernews-straight", "pokernews-ties"]
      },
      {
        "id": "pot-odds",
        "title": "Pot Odds and Required Equity",
        "scope": "Call-cost arithmetic, not a recommendation to call.",
        "paragraphs": [
          "Let P be the pot now: it includes the opponent's bet, all other committed wagers, and any chips already posted by the caller, but excludes the caller's unpaid call. Let C be the extra price to call, not the opponent's total raise when the caller has already invested chips. The reward-to-risk ratio is P:C; break-even equity = C / (P + C).",
          "For a 100 pot facing a 50 bet, P = 150 and C = 50: the final pot is 200, so break-even equity is 25%, not 33.33%. In a blind example, an open to 2.25bb plus a posted 1bb BB and 0.5bb SB gives P = 3.75bb; the BB's extra call is 1.25bb, requiring 25%."
        ],
        "bullets": [
          "The simple threshold assumes no rake, no further betting, and full realization of the estimated share of the eligible pot. Equality is break-even, not guaranteed profit. Ties contribute their share to equity.",
          "Rake, side-pot eligibility, future bet costs, implied/reverse implied odds, and equity realization can change call value. Raw draw-hit probability is not necessarily showdown equity; no live opponent range is supplied here."
        ],
        "tables": [
          {
            "caption": "Independently checked examples; same units within each row; percentages rounded to 6 decimals",
            "columns": ["Pot now P", "Extra call C", "Final pot P+C", "Break-even equity %"],
            "rows": [
              [150, 50, 200, 25],
              [175, 75, 250, 30],
              [200, 100, 300, 33.333333],
              [250, 150, 400, 37.5],
              [300, 200, 500, 40],
              [3.75, 1.25, 5, 25]
            ]
          }
        ],
        "source_ids": ["upswing-pot-odds"]
      },
      {
        "id": "outs-and-draws",
        "title": "Outs: Approximate and Exact",
        "scope": "Fixed-out draw-hit probability, not an equity calculator.",
        "paragraphs": [
          "An out is an unseen card that improves the hand toward the desired result. Count distinct cards once, then discount dirty outs that may leave the hand losing. An open-ended straight draw plus a flush draw can have 8 + 9 - 2 = 15 outs because two cards complete both draws.",
          "Rule of 2: about 2 x outs percent for one card. Rule of 4: about 4 x outs percent for both turn and river. A flop call normally buys only the turn; using the two-card estimate to justify that call ignores possible river costs. Even when all-in guarantees both cards, hitting a draw need not win.",
          "With only two hole cards and the board known, there are 47 unseen cards on the flop and 46 on the turn. For n fixed clean outs: flop -> turn = n/47; turn -> river = n/46; flop -> river = 1 - ((47-n)(46-n))/(47 x 46). The last expression also equals 1 - comb(47-n,2)/comb(47,2)."
        ],
        "bullets": [
          "These exact formulas count at least one card from a fixed out set under uniform unseen-card sampling. They do not model changing outs, backdoor draws needing two specific cards, opponent redraws, domination, or tied outcomes. Known dead/exposed cards change the counts.",
          "Rule of 4 overstates larger draws: 15 outs gives about 54.116559% to hit, not 60%. Rule of 2 is approximate too; 9 outs gives 19.148936% flop -> turn and 19.565217% turn -> river, not exactly 18%."
        ],
        "tables": [
          {
            "caption": "Common nominal out counts; improvement is not proof of winning",
            "columns": ["Outs", "Illustration"],
            "rows": [
              [2, "Pocket pair improving to three of a kind."],
              [4, "Gutshot straight draw."],
              [6, "Two overcards making a pair; these outs are often dirty."],
              [8, "Open-ended straight draw."],
              [9, "Four cards to a flush."],
              [15, "Open-ended straight plus flush draw, with two shared outs removed."]
            ]
          },
          {
            "caption": "Independently calculated fixed-out hit percentages, rounded to 6 decimals",
            "columns": ["Outs", "Flop -> turn %", "Turn -> river %", "Flop -> river %", "Rule of 2 %", "Rule of 4 %"],
            "rows": [
              [2, 4.255319, 4.347826, 8.418131, 4, 8],
              [4, 8.510638, 8.695652, 16.466235, 8, 16],
              [6, 12.765957, 13.043478, 24.144311, 12, 24],
              [8, 17.021277, 17.391304, 31.452359, 16, 32],
              [9, 19.148936, 19.565217, 34.967623, 18, 36],
              [15, 31.914894, 32.608696, 54.116559, 30, 60]
            ]
          }
        ],
        "source_ids": ["pokerology-outs", "upswing-pot-odds"]
      },
      {
        "id": "six-max-positions",
        "title": "Positions, Aliases and Action Order",
        "scope": "Monitor geometry is six-max only. Nine-handed names below are reference only. Standard dealt-in rosters, no straddle; physical slots are not poker positions.",
        "paragraphs": [
          "At six-max, UTG and LJ (lojack) name the same first non-blind position in this bundle; HJ (hijack) is the next seat. CO is cutoff, BTN is button, SB is small blind and BB is big blind. Our group convention is UTG/LJ early, HJ middle, CO/BTN late, with blinds separate. Educators differ on grouping HJ; exact names and action order are more precise than early/middle/late.",
          "Preflop opening action starts left of the BB and moves clockwise relative to the table. Postflop it starts with the first remaining player left of the button; BTN acts last when still in the hand. The tables give first-round order with everyone participating, not an assurance that a folded or all-in player acts. Later reopened betting follows the applicable rules.",
          "Positions belong to the original dealt-in roster for that hand. Folds do not relabel survivors, and a mid-hand arrival does not become a dealt-in participant. A new shorter-handed deal needs its own validated roster/button/blinds. RFI means raising first in after all earlier players folded, with only blinds posted."
        ],
        "bullets": [
          "A hand dealt heads-up uses BTN = SB: button/small blind acts first preflop and last postflop; BB acts last preflop and first postflop. Two survivors of a multiway hand retain their original positions; they are not automatically a new heads-up deal.",
          "Empty seats are not players, but a dead-button rule can place the button at an empty seat. Two occupied screen slots and a dealer marker do not prove a heads-up roster or a moving-button policy. Missing or ambiguous roster/button/blind evidence leaves positions unknown.",
          "Poker TDA 2026 rules 34 and 36-C establish tournament dead-button and heads-up conventions; Robert's Rules describes button/blind alternatives. Neither proves CoinPoker cash/practice policy or validates these screenshots.",
          "BB has no raise-first-in opportunity in an unopened pot: if all other players fold, the hand is over. Raising over an SB limp is an isolation raise, not RFI; facing an SB raise is defense, not RFI."
        ],
        "tables": [
          {
            "caption": "Six-max dealt roster: this bundle's grouping and actual opening order",
            "columns": ["Position / alias", "Group", "Preflop order", "Postflop order"],
            "rows": [
              ["UTG / LJ", "Early", 1, 3],
              ["HJ", "Middle", 2, 4],
              ["CO", "Late", 3, 5],
              ["BTN", "Late", 4, 6],
              ["SB", "Blind", 5, 1],
              ["BB", "Blind", 6, 2]
            ]
          },
          {
            "caption": "Nine-handed reference only: not nine-seat visual support",
            "columns": ["Position", "Group", "Preflop order", "Postflop order"],
            "rows": [
              ["UTG", "Early", 1, 3],
              ["UTG+1", "Early", 2, 4],
              ["UTG+2", "Early", 3, 5],
              ["LJ", "Middle", 4, 6],
              ["HJ", "Middle", 5, 7],
              ["CO", "Late", 6, 8],
              ["BTN", "Late", 7, 9],
              ["SB", "Blind", 8, 1],
              ["BB", "Blind", 9, 2]
            ]
          }
        ],
        "source_ids": ["pokerstars-position", "poker888-position-terms", "poker888-position-names", "pokernews-position", "tda-2026", "roberts-button", "upswing-six-max"]
      },
      {
        "id": "opening-examples",
        "title": "Contextual Opening Examples",
        "scope": "Strategy opinion for study, not live recommendations or an exact solver solution.",
        "paragraphs": [
          "These independently authored, relatively tight pure-raise examples assume an unopened six-max cash pot, approximately 100bb effective stacks, no antes or straddles, moderate capped pot rake, and typical non-extreme opponents. Example sizes are total raises to 2.5bb, or 3bb from SB, not extra chips on top of the blind. No frequencies or percentages are attributed to a source.",
          "Notation: s = suited, o = offsuit, T = ten. A pair plus includes higher pairs (55+ includes 55 through AA). For non-pairs, + keeps the higher rank fixed: ATo+ = ATo/AJo/AQo/AKo; 97s+ = 97s/98s. Each listed hand is a pure-open example, not a mixed-frequency prescription."
        ],
        "bullets": [
          "Later positions usually admit more hands because fewer players remain and postflop position improves. SB is special: only BB remains, but SB is out of position postflop. A limping strategy can also be reasonable there; this table only illustrates a pure-raise branch.",
          "Changing opening size, rake/cap, opponents' calling or 3-betting tendencies, effective stacks, or occupied seats changes applicability. Larger opens cost more when resisted; higher rake can eliminate marginal hands. These are not universal ranges, tournament/ICM ranges, or responses to a raise.",
          "The cited Upswing and GTO Wizard pages support adjustment principles, not these exact hand lists. GTO Wizard's large-raise study uses 125bb and 300bb examples, not a certification of this 100bb teaching baseline."
        ],
        "tables": [
          {
            "caption": "Authored RFI examples for the stated conditions only; BB is deliberately excluded",
            "columns": ["Position", "Example total open (bb)", "Illustrative hand range"],
            "rows": [
              ["UTG", 2.5, "55+, A2s+, KTs+, QTs+, JTs, T9s, 98s, ATo+, KJo+"],
              ["HJ", 2.5, "44+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+, QJo"],
              ["CO", 2.5, "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, A9o+, KTo+, QTo+, JTo"],
              ["BTN", 2.5, "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K8o+, Q9o+, J9o+, T9o"],
              ["SB", 3, "22+, A2s+, K2s+, Q6s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K9o+, Q9o+, J9o+, T9o"]
            ]
          }
        ],
        "source_ids": ["upswing-six-max", "gtowizard-large-opens"]
      },
      {
        "id": "facing-raises",
        "title": "Facing Raises, 3-Bets and 4-Bets",
        "scope": "Concepts and numbering only; no opponent-specific decision or live sizing advice.",
        "paragraphs": [
          "Preflop numbering counts the forced big blind as the first wager, the opening raise as the second (2-bet), a re-raise as the third (3-bet), and the next raise as a 4-bet. The SB is not a separate numbered level; calls do not increment the count. Postflop, the first voluntary bet is bet one, a raise is bet two, and a re-raise is bet three.",
          "RFI lists are not defense ranges. Facing a raise requires a separate fold/call/re-raise analysis using the opener's range and position, price, players behind, rake, blockers, fold equity, and effective stack. Heads-up effective stack is the smaller stack available to the two players; multiway side pots need separate treatment.",
          "AA is a premium value hand and often a 4-bet against a 3-bet, but a 4-bet is not automatically all-in. Non-all-in sizing can keep weaker hands or further raises in the pot. Position, effective stack, opponent response, and stack-to-pot ratio matter; the cited AA quiz's non-all-in preflop example is 150bb, not a universal 100bb size rule."
        ],
        "bullets": [
          "A tight early-position opening range and a loose button opening range need different responses. Out-of-position play and players still to act can reduce the attraction of calling; wide opponent calls and low fold equity reduce the value of pure bluff raises.",
          "Linear 3-bet ranges emphasize stronger hands together; polarized ranges combine value hands and selected weaker hands while some medium hands call. Blockers remove combinations, but alone do not make a raise profitable.",
          "Facing a 4-bet, earlier investments are sunk costs; new call price and remaining stack matter. Not every hand used to 3-bet can continue. Short all-in raises may not reopen action under the applicable rules; this reference is not a betting-legality engine."
        ],
        "tables": [
          {
            "caption": "Illustrative preflop numbering; amounts are totals, not sizing recommendations",
            "columns": ["Level", "Total wager (bb)", "Meaning"],
            "rows": [
              [1, 1, "Forced big blind."],
              [2, 2.5, "Opening raise."],
              [3, 9, "Re-raise of the opening raise."],
              [4, 22, "Raise of the 3-bet; not all-in with 100bb stacks."],
              [5, 100, "Further raise, here an illustrative all-in."]
            ]
          }
        ],
        "source_ids": ["upswing-bet-numbering", "upswing-three-bet", "upswing-aces", "gtowizard-large-opens"]
      },
      {
        "id": "glossary",
        "title": "Short Glossary",
        "scope": "Study terminology; these words are not evidence of observed live facts.",
        "paragraphs": [],
        "bullets": [],
        "tables": [
          {
            "caption": "Terms used in this reference",
            "columns": ["Term", "Meaning"],
            "rows": [
              ["bb", "One big blind as a unit; BB also names the big-blind seat."],
              ["RFI", "Raise first in: first voluntary entry is a raise after earlier players fold."],
              ["Range", "A set of possible hole-card hands; a detailed model may weight combinations."],
              ["Equity", "Expected share of the pot at showdown, including ties, against specified hands or ranges."],
              ["Out", "An unseen improving card; a dirty out may improve the hand without winning."],
              ["In position", "Acting after the relevant opponent on the postflop street."],
              ["Fold equity", "The value of opponents folding to aggression; not a measured live percentage here."],
              ["Blocker", "A known card that removes some combinations from opponents' possible holdings."],
              ["Effective stack", "Heads-up, the smaller stack available to the two players."],
              ["SPR", "Stack-to-pot ratio: remaining effective stack divided by the relevant pot size."],
              ["Rake", "The house fee; percentage, cap, and collection rules affect strategy."],
              ["Implied / reverse implied odds", "Potential future gains / extra losses after improving; neither is guaranteed."]
            ]
          }
        ],
        "source_ids": ["upswing-pot-odds", "pokerology-outs", "upswing-six-max", "upswing-three-bet", "upswing-aces"]
      },
      {
        "id": "limits-and-sources",
        "title": "Limitations and Source Use",
        "scope": "A locally bundled study summary, not a solver, chart import, or live recommendation system.",
        "paragraphs": [
          "All summaries and opening examples are independently authored. Citations point to retrieved educational passages supporting the concepts; pot and out tables are calculated independently, not copied from source images, PDFs, or range charts. Source strategy is opinion within its stated game assumptions, not a promise of profit.",
          "No runtime network is needed for this reference. Links are optional further reading. None of these sources validates screenshots, captured amounts, inferred seating, opponent tendencies, or this application's perception. Reading the reference does not enable advice or make recommendations live."
        ],
        "bullets": [
          "The scope is standard high-hand Hold'em. Omaha hole-card constraints, short-deck rankings, antes/straddles, tournament ICM, and short-stack push/fold strategies require different treatment.",
          "Percentages are rounded displays of exact arithmetic under explicit assumptions. Draw-hit estimates cannot substitute for a specified opponent range or full showdown equity and do not certify a profitable action.",
          "Sources were reviewed on the recorded UTC date; commercial education sites may change their text or availability. No paid chart, image, executable, or root-directory range asset is required."
        ],
        "tables": [],
        "source_ids": ["upswing-pot-odds", "pokerology-outs", "upswing-six-max", "gtowizard-large-opens", "upswing-aces"]
      }
    ]
  };
  /* END BUNDLED REFERENCE */

  const POLL_MS = 250;
  const REQUEST_TIMEOUT_MS = 1500;
  const HEARTBEAT_MAX_MS = 2500;
  const MAX_LEASE_MS = 5000;
  const MAX_RESPONSE_BYTES = 256 * 1024;
  const ACTIONS = ["fold", "check", "call", "bet", "raise", "all_in"];
  const ACTION_NAMES = { fold: "Fold", check: "Check", call: "Call", bet: "Bet", raise: "Raise", all_in: "All-in" };
  const CONTROL_NAMES = { ...ACTION_NAMES, raise: "Raise (re-raise)" };
  const ROLES = ["observing", "seated_waiting", "your_turn", "uncertain"];
  const ROLE_NAMES = { observing: "Observing", seated_waiting: "Seated / waiting", your_turn: "Your turn", uncertain: "Uncertain" };
  const ROLE_MESSAGES = { observing: "Watching the table", seated_waiting: "Waiting for your turn", your_turn: "Suggestions off", uncertain: "Reading uncertain" };
  const PHASE_NAMES = { preflop: "Preflop", flop: "Flop", turn: "Turn", river: "River", showdown: "Showdown", lobby: "Lobby", unseated: "Unseated", waiting: "Waiting", unknown: "Unknown" };
  const SEAT_LOCATIONS = ["Top", "Upper right", "Lower right", "Bottom", "Lower left", "Upper left"];
  const MODEL_STATES = ["disabled", "loading", "ready", "failed"];
  const CAPTURE_STATES = ["idle", "starting", "active", "unavailable", "disconnected", "blocked"];
  const SUITS = {
    s: { name: "spades", symbol: 0x2660, red: false },
    h: { name: "hearts", symbol: 0x2665, red: true },
    d: { name: "diamonds", symbol: 0x2666, red: true },
    c: { name: "clubs", symbol: 0x2663, red: false }
  };
  const SUIT_KEYS = { s: "s", spade: "s", spades: "s", h: "h", heart: "h", hearts: "h", d: "d", diamond: "d", diamonds: "d", c: "c", club: "c", clubs: "c" };
  const RANK_NAMES = { T: "Ten", J: "Jack", Q: "Queen", K: "King", A: "Ace" };
  const chipFormat = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const countFormat = new Intl.NumberFormat("en-US");
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  let snapshot = null;
  let connected = false;
  let session = null;
  let highestSequence = -1;
  const retiredSessions = new Set();
  let observationFloor = null;
  let closedLeaseKey = null;
  let recoveryAfterSequence = -1;
  let activeLease = null;
  let leaseTimer = null;
  let heartbeat = null;
  let heartbeatDeadline = 0;
  let heartbeatExpires = 0;
  let pollController = null;
  let pollTimer = null;
  let lifecycle = 0;
  let lastAnnouncement = "";
  let historyEvents = [];
  let referenceSections = [];
  let referenceLoaded = false;

  const node = (id) => document.getElementById(id);
  const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const integer = (value) => Number.isSafeInteger(value) && value >= 0;
  const seatNumber = (value) => integer(value) && value >= 1 && value <= 6;
  const percentage = (value) => Number.isFinite(value) && value >= 0 && value <= 100;
  const count = (value) => integer(value) ? countFormat.format(value) : "-";
  const chips = (value) => integer(value) ? `${chipFormat.format(value / 100)} chips` : "-";
  const percent = (value) => percentage(value) ? `${value.toFixed(1)}%` : "-";
  const allowed = (value, choices, fallback = null) => choices.includes(value) ? value : fallback;
  const opaqueId = (value) => typeof value === "string" && /^[A-Za-z0-9._:-]{1,96}$/.test(value);
  const safeLabel = (value, fallback, max = 200) => typeof value === "string" && value.trim() ? value.replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, "").slice(0, max) : fallback;

  function text(id, value) {
    const target = node(id);
    if (target.textContent !== value) target.textContent = value;
  }

  function make(tag, className, value) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (value !== undefined) result.textContent = value;
    return result;
  }

  function status(id, value, tone = "neutral") {
    text(id, value);
    node(id).dataset.tone = tone;
  }

  function announce(value) {
    if (value === lastAnnouncement) return;
    lastAnnouncement = value;
    text("announce", value);
  }

  async function getJson(path, controller) {
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(path, { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
      if (!response.ok || !response.body || !/\bapplication\/(?:[a-z0-9.-]+\+)?json\b/i.test(response.headers.get("content-type") || "")) throw new Error("unavailable");
      const length = Number(response.headers.get("content-length"));
      if (length > MAX_RESPONSE_BYTES) throw new Error("bounded response required");
      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        size += part.value.byteLength;
        if (size > MAX_RESPONSE_BYTES) {
          await reader.cancel();
          throw new Error("bounded response required");
        }
        chunks.push(part.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function normalizeCard(value) {
    if (!record(value) || typeof value.rank !== "string" || typeof value.suit !== "string") return null;
    const rank = value.rank.toUpperCase() === "10" ? "T" : value.rank.toUpperCase();
    const suitKey = value.suit.toLowerCase();
    const suit = Object.hasOwn(SUIT_KEYS, suitKey) ? SUIT_KEYS[suitKey] : null;
    return /^[2-9TJQKA]$/.test(rank) && suit ? { rank, suit } : null;
  }

  function normalizeObservation(value) {
    if (!record(value)) return null;
    if (!Array.isArray(value.hero_cards) || value.hero_cards.length > 2 || !Array.isArray(value.board) || value.board.length > 5) return null;
    const hero = value.hero_cards.map(normalizeCard);
    const board = value.board.map(normalizeCard);
    const seenCards = new Set();
    for (const card of [...hero, ...board]) {
      if (!card) return null;
      const key = card.rank + card.suit;
      if (seenCards.has(key)) return null;
      seenCards.add(key);
    }
    let role = allowed(value.role, ROLES);
    if (role === null) return null;
    const heroSeated = typeof value.hero_seated === "boolean" ? value.hero_seated : null;
    const actionRequired = typeof value.action_required === "boolean" ? value.action_required : null;
    if ((role === "observing" && (heroSeated !== false || actionRequired !== false)) ||
        (role === "seated_waiting" && (heroSeated !== true || actionRequired !== false)) ||
        (role === "your_turn" && (heroSeated !== true || actionRequired !== true))) role = "uncertain";
    const labels = new Map();
    if (Array.isArray(value.controls)) {
      for (const entry of value.controls.slice(0, 12)) {
        if (!record(entry) || !ACTIONS.includes(entry.action)) continue;
        let presence = allowed(entry.presence, ["present", "absent", "unknown"], "unknown");
        let enabled = allowed(entry.enabled, ["enabled", "disabled", "unknown"], "unknown");
        if (labels.has(entry.action) || (presence === "absent" && enabled === "enabled")) {
          presence = "unknown";
          enabled = "unknown";
        }
        labels.set(entry.action, { presence, enabled });
      }
    }
    // A listed action can establish presence only, never enabled state or absence of other controls.
    if (Array.isArray(value.available_actions) && value.available_actions.length > 0) {
      for (const action of value.available_actions.slice(0, 12)) {
        if (ACTIONS.includes(action) && !labels.has(action)) labels.set(action, { presence: "present", enabled: "unknown" });
      }
    }
    const phase = allowed(value.game_phase, Object.keys(PHASE_NAMES), "unknown");
    const amounts = {};
    for (const key of ["pot_size", "to_call", "acting_to_call", "hero_chips", "min_raise_to", "max_raise_to"]) {
      amounts[key] = record(value.amounts) && integer(value.amounts[key]) ? value.amounts[key] : null;
    }
    if (!seatNumber(value.acting_seat)) amounts.acting_to_call = null;
    if (heroSeated !== true || role === "uncertain" || phase === "unseated" || phase === "lobby") {
      for (const key of ["to_call", "hero_chips", "min_raise_to", "max_raise_to"]) amounts[key] = null;
    }
    if (role === "uncertain") labels.clear();
    const wagers = [];
    const wagerSeats = new Set();
    if (Array.isArray(value.wagers)) {
      if (value.wagers.length > 6) return null;
      for (const entry of value.wagers) {
        if (!record(entry) || !seatNumber(entry.seat) || wagerSeats.has(entry.seat)) return null;
        wagerSeats.add(entry.seat);
        wagers.push({ seat: entry.seat, amount: integer(entry.amount) ? entry.amount : null });
      }
    }
    return {
      generation: integer(value.generation) ? value.generation : null,
      epoch: integer(value.epoch) ? value.epoch : null,
      expires: integer(value.expires_at_unix_ms) ? value.expires_at_unix_ms : null,
      remaining: integer(value.remaining_ms) ? value.remaining_ms : null,
      captured: integer(value.captured_at_unix_ms) && value.captured_at_unix_ms > 0 ? value.captured_at_unix_ms : null,
      phase, role, heroSeated, actionRequired,
      actingSeat: seatNumber(value.acting_seat) ? value.acting_seat : null,
      hero: heroSeated === true ? hero : [], board, amounts, wagers, controls: labels,
      seats: SEAT_LOCATIONS.map((_, index) => ({ seat: index + 1, displayed_stack: null,
        visible_wager: wagers.find((entry) => entry.seat === index + 1)?.amount ?? null, street_contribution: null })),
      metrics: { rank: null, odds: null, draw: null, equity: null },
      partial: false,
      experimental: value.experimental === true
    };
  }

  function normalizePartialObservation(value) {
    if (!record(value) || value.quality_approved !== false || value.experimental !== true ||
        !Array.isArray(value.board_slots) || value.board_slots.length !== 5 ||
        !Array.isArray(value.seats) || value.seats.length !== 6) return null;
    const seats = new Map();
    for (const entry of value.seats) {
      if (!record(entry) || !seatNumber(entry.seat) || seats.has(entry.seat)) return null;
      // Only the server's per-field projection can qualify a wager; no capability upgrade here.
      const sceneFields = ["occupied", "status", "badge", "dealer", "small_blind", "big_blind", "acting"];
      const verifiedScene = Array.isArray(entry.scene_fields) && entry.scene_fields.length <= 7 ?
        new Set(entry.scene_fields.filter((field) => sceneFields.includes(field))) : new Set();
      const scene = Object.fromEntries(sceneFields.map((field) => [field, null]));
      for (const field of ["occupied", "dealer", "small_blind", "big_blind", "acting"]) {
        if (verifiedScene.has(field) && typeof entry[field] === "boolean") scene[field] = entry[field];
      }
      if (verifiedScene.has("status") && ["active", "folded", "all_in", "sitting_out"].includes(entry.status)) scene.status = entry.status;
      if (verifiedScene.has("badge") && ["none", "fold", "check", "call", "bet", "raise", "all_in", "small_blind", "big_blind"].includes(entry.badge)) scene.badge = entry.badge;
      seats.set(entry.seat, { seat: entry.seat, displayed_stack: integer(entry.displayed_stack) ? entry.displayed_stack : null,
        visible_wager: entry.visible_wager_status === "accepted" && integer(entry.visible_wager) ? entry.visible_wager : null,
        street_contribution: null, ...scene });
    }
    const board = value.board_slots.map(normalizeCard);
    const seen = new Set();
    const duplicates = new Set();
    for (const card of board.filter(Boolean)) {
      const key = card.rank + card.suit;
      if (seen.has(key)) duplicates.add(key);
      seen.add(key);
    }
    for (let i = 0; i < board.length; i += 1) if (board[i] && duplicates.has(board[i].rank + board[i].suit)) board[i] = null;
    let boardCount = [0, 3, 4, 5].includes(value.board_count) ? value.board_count : null;
    let phase = allowed(value.game_phase, ["preflop", "flop", "turn", "river", "showdown"], "unknown");
    const expected = { preflop: 0, flop: 3, turn: 4, river: 5, showdown: 5 };
    if (phase !== "unknown" && (boardCount !== null && boardCount !== expected[phase] || board.slice(expected[phase]).some(Boolean)) ||
        boardCount !== null && board.slice(boardCount).some(Boolean)) {
      phase = "unknown";
      boardCount = null;
      board.fill(null);
    }
    const seated = typeof value.hero_seated === "boolean" ? value.hero_seated : null;
    const role = value.role === "observing" && seated === false ? "observing" : "uncertain";
    return {
      generation: integer(value.generation) ? value.generation : null,
      epoch: integer(value.epoch) ? value.epoch : null,
      expires: integer(value.expires_at_unix_ms) ? value.expires_at_unix_ms : null,
      remaining: integer(value.remaining_ms) ? value.remaining_ms : null,
      captured: integer(value.captured_at_unix_ms) && value.captured_at_unix_ms > 0 ? value.captured_at_unix_ms : null,
      phase, role, heroSeated: seated, actionRequired: null,
      actingSeat: [...seats.values()].filter((entry) => entry.acting === true).length === 1 ?
        [...seats.values()].find((entry) => entry.acting === true).seat : null,
      hero: [], board, boardCount, amounts: { pot_size: integer(value.pot_size) ? value.pot_size : null,
        to_call: null, acting_to_call: null, hero_chips: null, min_raise_to: null, max_raise_to: null },
      seats: SEAT_LOCATIONS.map((_, index) => seats.get(index + 1)), wagers: [], controls: new Map(),
      metrics: { rank: null, odds: null, draw: null, equity: null }, partial: true, experimental: true
    };
  }

  function normalizeHistory(value) {
    const source = record(value) ? value : {};
    const counts = record(source.counts) ? source.counts : {};
    const events = [];
    if (Array.isArray(source.events)) {
      for (const entry of source.events.slice(-200)) {
        if (!record(entry)) continue;
        const kind = allowed(entry.kind, ["action", "gap", "boundary", "hand"]);
        if (kind === null) continue;
        events.push({
          kind: kind === "hand" ? "boundary" : kind,
          action: allowed(entry.action, ACTIONS),
          seat: seatNumber(entry.seat) ? entry.seat : null,
          amount: integer(entry.amount) ? entry.amount : null,
          allIn: entry.all_in === true,
          raiseOrdinal: ["bet", "raise"].includes(entry.action) && [3, 4].includes(entry.preflop_raise_ordinal) ? entry.preflop_raise_ordinal : null
        });
      }
    }
    return {
      state: allowed(source.state, ["unavailable", "partial"], "unavailable"),
      actions: integer(counts.observed_actions) ? counts.observed_actions : null,
      gaps: integer(source.gaps) ? source.gaps : null,
      counts: Object.fromEntries(["folds", "bets", "raises", "three_bets", "four_bets"].map((key) => [key, integer(counts[key]) ? counts[key] : null])),
      events
    };
  }

  function normalizeSnapshot(value) {
    if (!record(value) || value.schema_version !== 1 || !opaqueId(value.session_id) || !integer(value.event_seq)) return null;
    if (!["idle", "live"].includes(value.source)) return null;
    const server = value.server;
    const capture = value.capture;
    if (!record(server) || !MODEL_STATES.includes(server.model_state) || server.quality_gate !== "failed" || server.advice_ready !== false || value.advice !== null) return null;
    if (!record(capture) || !CAPTURE_STATES.includes(capture.state) || typeof capture.fresh_capture !== "boolean") return null;
    if (!integer(capture.frames) || typeof server.inference_busy !== "boolean" || typeof server.temperature_calibration_loaded !== "boolean") return null;
    if (!["UI_READY", "COLLECTOR_READY"].includes(value.readiness)) return null;
    return {
      session: value.session_id, sequence: value.event_seq, source: value.source,
      capture: {
        state: capture.state, fresh: capture.fresh_capture,
        heartbeat: integer(capture.last_heartbeat_unix_ms) && capture.last_heartbeat_unix_ms > 0 ? capture.last_heartbeat_unix_ms : null
      },
      observation: value.partial_observation != null ? normalizePartialObservation(value.partial_observation) : normalizeObservation(value.observation),
      history: normalizeHistory(value.history)
    };
  }

  function renderCards(id, cards, slots, label) {
    const fragment = document.createDocumentFragment();
    if (cards.length === 0) fragment.append(make("span", "unknown-value", "-"));
    for (let i = 0; i < Math.min(slots, cards.length); i += 1) {
      const card = cards[i];
      const item = make("div", "playing-card");
      item.setAttribute("role", "img");
      if (card) {
        const suit = SUITS[card.suit];
        item.classList.toggle("red-suit", suit.red);
        item.setAttribute("aria-label", `Experimental ${label} card ${i + 1}: ${RANK_NAMES[card.rank] || card.rank} of ${suit.name}`);
        item.append(make("span", "card-rank", card.rank), make("span", "card-suit", String.fromCodePoint(suit.symbol)));
      } else {
        item.classList.add("unknown-card");
        item.setAttribute("aria-label", `${label} card ${i + 1}: unknown, no verified card`);
        item.append(make("span", "card-rank", "-"));
      }
      fragment.append(item);
    }
    node(id).replaceChildren(fragment);
  }

  function renderControls(id, labels) {
    const fragment = document.createDocumentFragment();
    for (const action of ACTIONS) {
      const value = labels ? labels.get(action) : null;
      if (!value || value.presence !== "present") continue;
      const item = make("li", "control-label");
      item.dataset.enabled = value.enabled;
      item.append(make("span", "", CONTROL_NAMES[action]), make("span", "control-state", value.enabled === "unknown" ? "state unknown" : value.enabled));
      fragment.append(item);
    }
    if (!fragment.childNodes.length) fragment.append(make("li", "unknown-value", "-"));
    node(id).replaceChildren(fragment);
  }

  function amount(id, value) {
    text(id, chips(value));
    node(id).classList.toggle("unknown-value", !integer(value));
  }

  function renderAction(observation) {
    const role = observation ? observation.role : "uncertain";
    node("suggested-action").hidden = !observation;
    node("suggested-action").dataset.role = role;
    status("role-status", ROLE_NAMES[role], role === "your_turn" ? "warning" : "neutral");
    node("role-status").hidden = role === "uncertain";
    text("action-move", ROLE_MESSAGES[role]);
    text("action-amount", "-");
    node("action-amount-wrap").hidden = true;
    text("action-reason", role === "observing" ? "Readings and history continue while you observe." :
      role === "seated_waiting" ? "Readings and history continue between turns." : "Suggestions stay off until seated readings are validated.");
    node("action-reason").hidden = role === "uncertain";
  }

  function renderObservation(observation) {
    renderAction(observation);
    const readable = !!observation && (!observation.partial || observation.phase !== "unknown" ||
      observation.boardCount !== null || observation.board.some(Boolean) || observation.amounts.pot_size !== null ||
      observation.seats.some((entry) => entry.displayed_stack !== null || entry.visible_wager !== null ||
        [entry.occupied, entry.status, entry.badge, entry.dealer, entry.small_blind, entry.big_blind, entry.acting].some((v) => v != null)));
    node("monitor-readings").hidden = !readable;
    node("monitor-empty").hidden = readable;
    node("monitor-grid").classList.toggle("no-reading", !observation);
    node("history-panel").hidden = !observation || node("monitor-grid").classList.contains("no-history");
    if (!readable) text("monitor-empty", observation ? "Reading uncertain" : connected && snapshot && snapshot.capture.state === "blocked" ?
      "Waiting for a unique CoinPoker game window." : connected && snapshot && snapshot.source === "live" ?
        "Reading uncertain" : "Waiting for a table reading.");
    renderCards("hero-cards", observation ? observation.hero : [], 2, "Hero");
    const board = observation ? observation.partial ? observation.board.slice(0, observation.boardCount ??
      observation.board.reduce((last, card, index) => card ? index + 1 : last, 0)) : observation.board : [];
    renderCards("board-cards", board, 5, "Board");
    if (observation?.partial && observation.boardCount === 0) text("board-cards", "No community cards");
    node("hero-card-group").hidden = !observation || observation.heroSeated !== true;
    renderControls("control-states", observation ? observation.controls : null);
    text("game-phase", observation && observation.phase !== "unknown" ? PHASE_NAMES[observation.phase] : "-");
    text("acting-seat", observation && observation.actingSeat !== null ? `Seat ${observation.actingSeat}` : "-");
    const observing = observation && observation.role === "observing";
    const seated = observation && ["seated_waiting", "your_turn"].includes(observation.role);
    text("call-label", observing ? observation.actingSeat === null ? "Acting-seat call" : `Acting seat ${observation.actingSeat} to call` : seated ? "Your call" : "Call");
    amount("amount-call", observation ? observing ? observation.amounts.acting_to_call : seated ? observation.amounts.to_call : null : null);
    for (const [id, key] of [["amount-pot", "pot_size"], ["amount-stack", "hero_chips"], ["amount-min", "min_raise_to"], ["amount-max", "max_raise_to"]]) amount(id, observation ? observation.amounts[key] : null);
    node("hero-stack-reading").hidden = !seated;
    node("call-reading").hidden = !observation || observation.partial;
    node("actor-reading").hidden = !observation || observation.actingSeat === null;
    node("controls-reading").hidden = !observation || observation.partial;
    node("raise-bounds").hidden = !observation || observation.amounts.min_raise_to === null && observation.amounts.max_raise_to === null;
    const wagers = document.createDocumentFragment();
    for (const entry of observation ? observation.wagers : []) {
      const item = make("li");
      item.append(make("span", "wager-seat", `Seat ${entry.seat}`), make("span", "mono", chips(entry.amount)));
      wagers.append(item);
    }
    if (!wagers.childNodes.length) wagers.append(make("li", "unknown-value", "-"));
    node("visible-wagers").replaceChildren(wagers);
    node("wagers-reading").hidden = !observation || observation.partial;
    const seatGrid = document.createDocumentFragment();
    for (const entry of observation ? observation.seats : []) {
      const item = make("li", "seat-reading");
      item.dataset.seat = String(entry.seat);
      const heading = make("div", "seat-heading");
      heading.append(make("h4", "", `Seat ${entry.seat}`), make("span", "seat-location", SEAT_LOCATIONS[entry.seat - 1]));
      const markers = [entry.occupied === true ? "Occupied" : entry.occupied === false ? "Open" : null,
        entry.status?.replaceAll("_", " "), entry.dealer === true ? "BTN" : null,
        entry.small_blind === true ? "SB" : null, entry.big_blind === true ? "BB" : null,
        entry.acting === true ? "Acting" : null, entry.badge && entry.badge !== "none" ? `Badge: ${entry.badge.replaceAll("_", " ")}` : null];
      if (markers.some(Boolean)) heading.append(make("span", "seat-location", markers.filter(Boolean).join(" / ")));
      const amounts = make("dl", "seat-amounts");
      for (const [label, key] of [["Displayed stack", "displayed_stack"], ["Visible wager", "visible_wager"], ["Street contribution", "street_contribution"]]) {
        const field = make("div");
        field.append(make("dt", "", label), make("dd", integer(entry[key]) ? "" : "unknown-value", chips(entry[key])));
        amounts.append(field);
      }
      item.append(heading, amounts);
      seatGrid.append(item);
    }
    node("seat-readings").replaceChildren(seatGrid);
    node("seats-reading").hidden = !observation;
    const metrics = observation ? observation.metrics : {};
    const oddsSeat = observing ? observation.actingSeat : metrics.odds ? metrics.odds.seat : null;
    text("metric-odds-label", observing ? oddsSeat === null ? "Acting-seat pot odds / required equity" : `Seat ${oddsSeat} pot odds / required equity` : "Pot odds / required equity");
    text("metric-rank", metrics.rank || "-");
    text("metric-odds", percent(metrics.odds ? metrics.odds.pct : null));
    text("metric-draw-outs", count(metrics.draw ? metrics.draw.outs : null));
    text("metric-draw-next", percent(metrics.draw ? metrics.draw.next : null));
    text("metric-draw-river", percent(metrics.draw ? metrics.draw.river : null));
    text("metric-equity", percent(metrics.equity));
    node("metrics-readings").hidden = true;
    text("reading-limit", observation?.partial ? (observation.seats.some((entry) => entry.visible_wager !== null ||
      entry.occupied != null || entry.status != null || entry.badge != null) ?
      "Seat fields have separate evidence. Hand positions, street contributions and math require validated context. Suggestions off." :
      "Wagers, street contributions and seat markers are untrained; unknown. Metrics and suggestions off.") :
      "A dash is unknown. Metrics and suggestions off.");
  }

  function captureHealthy() {
    return connected && snapshot && snapshot.source === "live" && snapshot.capture.state === "active" && snapshot.capture.fresh && snapshot.capture.heartbeat !== null && Date.now() < heartbeatExpires && performance.now() < heartbeatDeadline;
  }

  function renderHistory(value) {
    historyEvents = value ? value.events : [];
    const visible = !!value && (historyEvents.length > 0 || value.actions !== null || value.gaps > 0 || Object.values(value.counts).some((entry) => entry !== null));
    node("history-panel").hidden = !activeLease || !visible;
    node("monitor-grid").classList.toggle("no-history", !visible);
    status("history-status", connected ? "Partial" : "Partial / offline", "warning");
    for (const [id, key] of [["history-folds", "folds"], ["history-bets", "bets"], ["history-raises", "raises"], ["history-three-bets", "three_bets"], ["history-four-bets", "four_bets"]]) text(id, count(value ? value.counts[key] : null));
    text("history-gaps", count(value ? value.gaps : null));
    text("history-coverage", connected ? "Partial history; gaps may hide actions." : "Saved partial history; gaps may hide actions.");
    renderHistoryEvents();
  }

  function renderHistoryEvents() {
    const filter = node("history-filter").value;
    const events = historyEvents.filter((entry) => filter === "all" || entry.kind === filter).reverse();
    const fragment = document.createDocumentFragment();
    for (const entry of events) {
      const item = make("li", entry.kind === "gap" ? "event-row gap-event" : "event-row");
      let label = entry.kind === "gap" ? "Coverage gap" : "Hand or table changed";
      if (entry.kind === "action") label = entry.action ? `Observed ${entry.raiseOrdinal === null ? ACTION_NAMES[entry.action] : `${entry.raiseOrdinal}-bet`}${entry.allIn ? " / all-in" : ""}` : "Action observed / subtype unknown";
      const details = [];
      if (entry.amount !== null) details.push(chips(entry.amount));
      if (entry.kind === "gap") details.push("Some actions may be missing.");
      item.append(make("span", "event-seat", entry.seat === null ? "-" : `Seat ${entry.seat}`), make("span", "event-label", label), make("span", "event-detail", details.join(" / ")));
      fragment.append(item);
    }
    node("history-events").replaceChildren(fragment);
    node("history-empty").hidden = events.length > 0;
    text("history-empty", historyEvents.length > 0 ? "No activity matches this filter." : "No actions recorded in this partial history.");
  }

  const leaseKey = (observation) => `${session}:${observation.epoch}:${observation.generation}`;
  const compareObservation = (a, b) => a.epoch < b.epoch || a.generation < b.generation ? -1 :
    a.epoch > b.epoch || a.generation > b.generation ? 1 : 0;

  function closeObservation(observation) {
    if (!observation || observation.epoch === null || observation.generation === null) return;
    if (!observationFloor || compareObservation(observation, observationFloor) >= 0) {
      observationFloor = { epoch: observation.epoch, generation: observation.generation };
      closedLeaseKey = leaseKey(observation);
    }
  }

  function clearObservation() {
    const wasActive = activeLease !== null;
    closeObservation(activeLease ? activeLease.observation : snapshot ? snapshot.observation : null);
    activeLease = null;
    window.clearTimeout(leaseTimer);
    leaseTimer = null;
    renderObservation(null);
    if (wasActive) announce("Table reading cleared. Suggestions remain off.");
  }

  function disconnected() {
    connected = false;
    recoveryAfterSequence = Math.max(recoveryAfterSequence, highestSequence);
    clearObservation();
    renderHistory(snapshot ? snapshot.history : null);
    text("monitor-empty", "Table disconnected. Waiting for a fresh reading.");
    announce("Table disconnected. Suggestions remain off.");
  }

  function updateHeartbeat(value) {
    const time = value.capture.heartbeat;
    const wall = Date.now();
    const monotonic = performance.now();
    if (time === null || time > wall + 500 || (heartbeat !== null && time < heartbeat)) {
      heartbeatDeadline = 0;
      heartbeatExpires = 0;
      return;
    }
    const expires = time + HEARTBEAT_MAX_MS;
    const deadline = monotonic + Math.max(0, Math.min(HEARTBEAT_MAX_MS, expires - wall));
    if (heartbeat === time) {
      heartbeatDeadline = Math.min(heartbeatDeadline, deadline);
      heartbeatExpires = Math.min(heartbeatExpires, expires);
    } else {
      heartbeat = time;
      heartbeatDeadline = deadline;
      heartbeatExpires = expires;
    }
  }

  function admitObservation(value, previousSequence, roundTripMs) {
    const observation = value.observation;
    if (!observation) {
      clearObservation();
      return;
    }
    if (!captureHealthy() || !observation.experimental || observation.generation === null || observation.epoch === null || observation.captured === null || observation.expires === null || observation.remaining === null) {
      closeObservation(observation);
      clearObservation();
      return;
    }
    const key = leaseKey(observation);
    const comparison = observationFloor ? compareObservation(observation, observationFloor) : 1;
    if (comparison < 0 || key === closedLeaseKey || value.sequence <= recoveryAfterSequence) {
      clearObservation();
      return;
    }
    const sameLease = activeLease && activeLease.key === key;
    if (sameLease && observation.captured !== activeLease.observation.captured) {
      closeObservation(observation);
      clearObservation();
      return;
    }
    if (!sameLease && previousSequence >= 0 && value.sequence <= previousSequence) {
      closeObservation(observation);
      clearObservation();
      return;
    }
    const wall = Date.now();
    const monotonic = performance.now();
    const remaining = Math.min(MAX_LEASE_MS, observation.remaining - roundTripMs, observation.expires - wall);
    if (remaining <= 0 || observation.captured > wall || observation.expires <= observation.captured || observation.expires > observation.captured + MAX_LEASE_MS) {
      closeObservation(observation);
      clearObservation();
      return;
    }
    // Repeated polls can only shorten a lease. A new event sequence alone cannot renew it.
    const deadline = sameLease ? Math.min(activeLease.deadline, monotonic + remaining) : monotonic + remaining;
    const expires = sameLease ? Math.min(activeLease.expires, observation.expires) : observation.expires;
    const previousRole = activeLease ? activeLease.observation.role : null;
    activeLease = { key, deadline, expires, observation };
    observationFloor = { epoch: observation.epoch, generation: observation.generation };
    closedLeaseKey = null;
    window.clearTimeout(leaseTimer);
    leaseTimer = window.setTimeout(refreshClocks, Math.max(0, Math.min(deadline - monotonic, expires - wall)) + 1);
    renderObservation(observation);
    if (previousRole !== observation.role) announce(`${ROLE_MESSAGES[observation.role]}. Suggestions remain off.`);
  }

  function acceptSnapshot(value, roundTripMs) {
    if (retiredSessions.has(value.session)) {
      disconnected();
      return;
    }
    const changedSession = session !== null && value.session !== session;
    if (changedSession) {
      if (retiredSessions.size >= 64) {
        disconnected();
        return;
      }
      clearObservation();
      retiredSessions.add(session);
      session = value.session;
      highestSequence = -1;
      observationFloor = null;
      closedLeaseKey = null;
      recoveryAfterSequence = value.sequence;
      heartbeat = null;
      heartbeatDeadline = 0;
      heartbeatExpires = 0;
    } else if (session === null) session = value.session;
    if (value.sequence < highestSequence) {
      disconnected();
      return;
    }
    const previousSequence = highestSequence;
    highestSequence = value.sequence;
    const connectionChanged = !connected;
    snapshot = value;
    connected = true;
    updateHeartbeat(value);
    renderHistory(value.history);
    if (changedSession) {
      closeObservation(value.observation);
      clearObservation();
    } else admitObservation(value, previousSequence, roundTripMs);
    if (connectionChanged && !activeLease) announce("Waiting for a table reading. Suggestions remain off.");
    refreshClocks();
  }

  function refreshClocks() {
    if (!connected || !snapshot || document.hidden) return;
    const wall = Date.now();
    const monotonic = performance.now();
    if (snapshot.capture.state === "active" && !captureHealthy()) {
      if (activeLease) clearObservation();
    }
    if (!activeLease) return;
    if (wall >= activeLease.expires || monotonic >= activeLease.deadline) {
      clearObservation();
    }
  }

  function schedulePoll(delay) {
    window.clearTimeout(pollTimer);
    if (!document.hidden) pollTimer = window.setTimeout(poll, delay);
  }

  async function poll() {
    if (document.hidden) return;
    if (pollController) {
      schedulePoll(POLL_MS);
      return;
    }
    const version = lifecycle;
    const controller = new AbortController();
    pollController = controller;
    const started = performance.now();
    try {
      const raw = await getJson("/api/state", controller);
      if (version !== lifecycle || document.hidden) return;
      const value = normalizeSnapshot(raw);
      if (!value) {
        disconnected();
        return;
      }
      acceptSnapshot(value, performance.now() - started);
    } catch {
      if (version === lifecycle && !document.hidden) disconnected();
    } finally {
      if (pollController === controller) pollController = null;
      if (version === lifecycle) schedulePoll(Math.max(0, POLL_MS - (performance.now() - started)));
    }
  }

  function suspend() {
    lifecycle += 1;
    window.clearTimeout(pollTimer);
    if (pollController) pollController.abort();
    disconnected();
  }

  function resume() {
    lifecycle += 1;
    clearObservation();
    text("monitor-empty", "Waiting for a fresh table reading.");
    schedulePoll(0);
  }

  function showTab(tab, focus = false) {
    for (const candidate of tabs) {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      node(candidate.getAttribute("aria-controls")).hidden = !selected;
    }
    if (focus) tab.focus();
    const name = tab.id.slice(4);
    const labels = { monitor: "Experimental readings / suggestions off", reference: "Local reference / not live guidance" };
    text("view-label", labels[name]);
    if (name === "reference" && !referenceLoaded) loadReference();
  }

  function httpsUrl(value) {
    if (typeof value !== "string" || value.length > 2048 || /[\s\u0000-\u001f\u007f]/.test(value)) return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && url.hostname && !url.username && !url.password ? url.href : null;
    } catch {
      return null;
    }
  }

  function normalizeReference(value) {
    if (!record(value) || value.schema_version !== 1 || !Array.isArray(value.sources) || value.sources.length > 32 || !Array.isArray(value.sections) || value.sections.length === 0 || value.sections.length > 24) return null;
    if (typeof value.title !== "string" || typeof value.scope !== "string" || typeof value.reviewed_utc !== "string" || !Number.isFinite(Date.parse(value.reviewed_utc))) return null;
    const sources = new Map();
    for (const source of value.sources) {
      if (!record(source) || !opaqueId(source.id) || sources.has(source.id) || typeof source.title !== "string" || typeof source.publisher !== "string" || typeof source.url !== "string") return null;
      sources.set(source.id, { title: safeLabel(source.title, source.id, 160), publisher: safeLabel(source.publisher, "", 100), url: httpsUrl(source.url) });
    }
    const sections = [];
    const ids = new Set();
    let cells = 0;
    for (const section of value.sections) {
      if (!record(section) || !opaqueId(section.id) || ids.has(section.id) || typeof section.title !== "string" || typeof section.scope !== "string") return null;
      if (!Array.isArray(section.paragraphs) || section.paragraphs.length > 16 || !section.paragraphs.every((entry) => typeof entry === "string") || !Array.isArray(section.bullets) || section.bullets.length > 40 || !section.bullets.every((entry) => typeof entry === "string")) return null;
      if (!Array.isArray(section.tables) || section.tables.length > 4 || !Array.isArray(section.source_ids) || section.source_ids.length > 32 || !section.source_ids.every((id) => sources.has(id))) return null;
      ids.add(section.id);
      const tables = [];
      for (const table of section.tables) {
        if (!record(table) || typeof table.caption !== "string" || !Array.isArray(table.columns) || table.columns.length === 0 || table.columns.length > 8 || !table.columns.every((entry) => typeof entry === "string") || !Array.isArray(table.rows) || table.rows.length > 48) return null;
        cells += table.rows.length * table.columns.length;
        if (cells > 2048 || !table.rows.every((row) => Array.isArray(row) && row.length === table.columns.length && row.every((cell) => typeof cell === "string" || typeof cell === "number" && Number.isFinite(cell)))) return null;
        tables.push({ caption: safeLabel(table.caption, "", 240), columns: table.columns.map((entry) => safeLabel(entry, "", 100)), rows: table.rows.map((row) => row.map((cell) => typeof cell === "string" ? safeLabel(cell, "", 500) : cell)) });
      }
      sections.push({ id: section.id, title: safeLabel(section.title, section.id, 160), scope: safeLabel(section.scope, "", 800), paragraphs: section.paragraphs.map((entry) => safeLabel(entry, "", 2000)), bullets: section.bullets.map((entry) => safeLabel(entry, "", 1200)), tables, sources: [...new Set(section.source_ids)].map((id) => sources.get(id)) });
    }
    return { title: safeLabel(value.title, "Poker reference", 160), scope: safeLabel(value.scope, "", 800), reviewed: value.reviewed_utc, sections };
  }

  function loadReference() {
    try {
      const value = normalizeReference(LOCAL_REFERENCE);
      if (!value) throw new Error("reference contract required");
      const fragment = document.createDocumentFragment();
      const rendered = [];
      for (const [index, section] of value.sections.entries()) {
        const detail = make("details", "reference-section");
        detail.dataset.sectionId = section.id;
        const summary = make("summary");
        const number = make("span", "reference-number", String(index + 1).padStart(2, "0"));
        number.setAttribute("aria-hidden", "true");
        summary.append(number, make("h3", "", section.title));
        const content = make("div", "reference-content");
        if (section.scope) content.append(make("p", "reference-scope", section.scope));
        for (const paragraph of section.paragraphs) content.append(make("p", "", paragraph));
        if (section.bullets.length) {
          const bullets = make("ul", "reference-bullets");
          for (const bullet of section.bullets) bullets.append(make("li", "", bullet));
          content.append(bullets);
        }
        for (const entry of section.tables) {
          const scroll = make("div", "table-scroll");
          scroll.tabIndex = 0;
          scroll.setAttribute("role", "region");
          scroll.setAttribute("aria-label", entry.caption || section.title);
          const table = make("table");
          table.append(make("caption", "", entry.caption));
          const heading = make("thead");
          const columns = make("tr");
          for (const column of entry.columns) {
            const cell = make("th", "", column);
            cell.scope = "col";
            columns.append(cell);
          }
          heading.append(columns);
          const body = make("tbody");
          for (const values of entry.rows) {
            const row = make("tr");
            for (const cell of values) row.append(make("td", "", cell));
            body.append(row);
          }
          table.append(heading, body);
          scroll.append(table);
          content.append(scroll);
        }
        if (section.sources.length) {
          const sources = make("ul", "source-links");
          sources.setAttribute("aria-label", "Sources");
          for (const source of section.sources) {
            const item = make("li");
            const citation = make(source.url ? "a" : "span", "", source.title);
            if (source.url) {
              citation.href = source.url;
              citation.target = "_blank";
              citation.rel = "noopener noreferrer";
              citation.referrerPolicy = "no-referrer";
            }
            item.append(make("span", "source-publisher", source.publisher), citation);
            sources.append(item);
          }
          content.append(make("h4", "source-heading", "Sources"), sources);
        }
        detail.append(summary, content);
        fragment.append(detail);
        const searchText = [section.title, section.scope, ...section.paragraphs, ...section.bullets, ...section.tables.flatMap((table) => [table.caption, ...table.columns, ...table.rows.flat()]), ...section.sources.flatMap((source) => [source.title, source.publisher])].join(" ").normalize("NFKC").toLowerCase();
        rendered.push({ detail, searchText });
      }
      node("reference-sections").replaceChildren(fragment);
      referenceSections = rendered;
      text("reference-title", value.title);
      text("reference-scope", value.scope);
      text("reference-reviewed", `Reviewed ${new Date(value.reviewed).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`);
      node("reference-search").disabled = false;
      node("reference-load-status").hidden = true;
      referenceLoaded = true;
      filterReference();
    } catch {
      referenceSections = [];
      node("reference-sections").replaceChildren();
      node("reference-search").disabled = true;
      node("reference-load-status").hidden = false;
      status("reference-load-status", "Local reference could not be read. No facts have been substituted.", "warning");
    }
  }

  function filterReference() {
    const words = node("reference-search").value.slice(0, 160).normalize("NFKC").toLowerCase().trim().split(/\s+/).filter(Boolean);
    let matches = 0;
    for (const entry of referenceSections) {
      const match = words.every((word) => entry.searchText.includes(word));
      entry.detail.hidden = !match;
      if (match) {
        matches += 1;
        if (words.length) entry.detail.open = true;
      }
    }
    node("reference-empty").hidden = matches > 0;
    text("reference-count", words.length ? `${matches} of ${referenceSections.length} topics` : `${referenceSections.length} topics`);
  }

  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener("click", () => showTab(tab));
    tab.addEventListener("keydown", (event) => {
      let target = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") target = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = (index + tabs.length - 1) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      if (target !== null) {
        event.preventDefault();
        showTab(tabs[target], true);
      }
    });
  }
  node("history-filter").addEventListener("change", renderHistoryEvents);
  node("reference-search").addEventListener("input", filterReference);
  document.addEventListener("visibilitychange", () => document.hidden ? suspend() : resume());
  window.addEventListener("pagehide", suspend);
  window.addEventListener("pageshow", (event) => { if (event.persisted && !document.hidden) resume(); });
  renderObservation(null);
  renderHistory(null);
  window.setInterval(refreshClocks, 100);
  if (!document.hidden) schedulePoll(0);
})();
