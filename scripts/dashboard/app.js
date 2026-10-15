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
  const SUSTAINED_RECEIPT_MAX_MS = 3000;
  const MAX_RESPONSE_BYTES = 256 * 1024;
  const ACTIONS = ["fold", "check", "call", "bet", "raise", "all_in"];
  const ACTION_NAMES = { fold: "Fold", check: "Check", call: "Call", bet: "Bet", raise: "Raise", all_in: "All-in" };
  const CONTROL_NAMES = { ...ACTION_NAMES, raise: "Raise (re-raise)" };
  const ROLES = ["observing", "seated_waiting", "your_turn", "uncertain"];
  const ROLE_NAMES = { observing: "Observing", seated_waiting: "Seated / waiting", your_turn: "Your turn", uncertain: "Uncertain" };
  const ROLE_MESSAGES = { observing: "Watching the table", seated_waiting: "Waiting for your turn", your_turn: "Analysis unavailable", uncertain: "Reading uncertain" };
  const HAND_RANKS = ["High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush"];
  const PHASE_NAMES = { preflop: "Preflop", flop: "Flop", turn: "Turn", river: "River", showdown: "Showdown", lobby: "Lobby", unseated: "Unseated", waiting: "Waiting", unknown: "Unknown" };
  const SEAT_LOCATIONS = ["Top", "Upper right", "Lower right", "Bottom", "Lower left", "Upper left"];
  const FIELD_REASONS = { "missing-capability": "Untrained", "unsupported-layout": "Unsupported layout",
    "below-floor": "Below floor", stale: "Stale", occluded: "Occluded", "insufficient-context": "Insufficient context" };
  const MODEL_STATES = ["disabled", "loading", "ready", "failed"];
  const CAPTURE_STATES = ["idle", "starting", "verifying", "active", "unavailable", "disconnected", "blocked"];
  const AUTOMATIC_LABELS = { "waiting-model": "Waiting for model", searching: "Searching for table",
    verifying: "Verifying table activity", active: "Waiting for table receipt",
    stopped: "Automatic observation stopped", failed: "Automatic observation failed",
    interrupted: "Automatic observation interrupted", idle: "Automatic observation idle" };
  const ACTIVITY_LABELS = { searching: "Searching for table", verifying: "Verifying table activity",
    active: "Observing active table", idle: "Automatic observation idle" };
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
  let adviceLease = null;
  let closedAdviceKey = null;
  let fullSourceLease = null;
  let fullBinding = null;
  let leaseTimer = null;
  let recordingLease = null;
  let recordingSeen = false;
  const retiredRecordings = new Set();
  let heartbeat = null;
  let heartbeatDeadline = 0;
  let heartbeatExpires = 0;
  let pollController = null;
  let pollTimer = null;
  let startController = null;
  let startRequest = null;
  let stopController = null;
  let stopRequest = null;
  let lifecycle = 0;
  let lastAnnouncement = "";
  let historyEvents = [];
  let referenceSections = [];
  let referenceLoaded = false;
  let selectedTopic = null;
  let clearReason = "insufficient-context";
  let retainedScope = null;
  const retainedNumbers = new Map();
  const numericSupersession = new Map();
  const retainedIdentities = new Map();
  let experimentalLease = null;
  let experimentalFloor = null;
  let experimentalClosedKey = null;
  let experimentalBinding = null;
  let visualLease = null;
  let historicalVisual = null;
  let visualFloor = null;
  let numericLease = null;
  let numericFloor = null;
  let contextLease = null;
  let contextFloor = null;
  let tableBinding = null;
  let tableBoundaryCapture = null;
  let confirmedTableId = null;
  let contextSourceBinding = null;
  let selectedSeat = null;
  let selectedOccupant = null;
  let selectedAssociationChanged = false;
  let tableNodes = null;
  const occupantFences = new Map();
  const renderedFields = new Map();
  const sourceAges = new Map();
  const renderReceipts = [];
  let droppedRenderReceipts = 0;
  const RENDER_RECEIPT_LIMIT = 12000;
  const PROFILE_METRICS = [["vpip", "VPIP"], ["pfr", "PFR"], ["three_bet", "3-BET"], ["c_bet", "C-BET"]];
  const EXPERIMENTAL_SCENE = { occupied: ["occupied", "open", "unknown"],
    status: ["active", "folded", "all_in", "sitting_out", "unknown"],
    badge: ["none", "fold", "check", "call", "bet", "raise", "all_in", "small_blind", "big_blind", "unknown"],
    dealer: ["dealer_here", "not_dealer", "unknown"], small_blind: ["small_blind_here", "not_small_blind", "unknown"],
    big_blind: ["big_blind_here", "not_big_blind", "unknown"], acting: ["yes", "no", "unknown"] };

  const node = (id) => document.getElementById(id);
  const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const integer = (value) => Number.isSafeInteger(value) && value >= 0;
  const chipAmount = (value) => integer(value) && value <= 4294967295;
  const sourceId = (value) => typeof value === "string" && /^[0-9a-f]{16}$/.test(value);
  const controlId = (value) => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
  const seatNumber = (value) => integer(value) && value >= 1 && value <= 6;
  const percentage = (value) => Number.isFinite(value) && value >= 0 && value <= 100;
  const count = (value) => integer(value) ? countFormat.format(value) : "-";
  const chips = (value) => integer(value) ? `${chipFormat.format(value / 100)} chips` : "-";
  // Coarse display only; source ages and expiry checks retain millisecond precision.
  const ageSummary = (ms) => ms < 5000 ? "under 5s" : ms < 60000 ?
    `${Math.floor(ms / 5000) * 5}s+` : `${count(Math.floor(ms / 60000))}m+`;
  const literalAmount = (value, literal) => {
    if (!integer(value)) return "-";
    if (typeof literal === "string" && literal.length <= 32 && /^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?$/.test(literal)) {
      const [whole, fraction = ""] = literal.replaceAll(",", "").split(".");
      if (Number(whole + fraction.padEnd(2, "0")) === value) return literal;
    }
    return chips(value);
  };
  const percent = (value) => percentage(value) ? `${value.toFixed(1)}%` : "-";
  const allowed = (value, choices, fallback = null) => choices.includes(value) ? value : fallback;
  const opaqueId = (value) => typeof value === "string" && /^[A-Za-z0-9._:-]{1,96}$/.test(value);
  const automaticPolicy = (value) => ["automatic-bounded", "automatic-sustained"].includes(value);
  const safeLabel = (value, fallback, max = 200) => typeof value === "string" && value.trim() ? value.replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, "").slice(0, max) : fallback;

  function fieldStatuses(value) {
    if (!record(value)) return {};
    const result = {};
    for (const [key, entry] of Object.entries(value).slice(0, 128)) {
      if (!/^(?:game_phase|board|board_count|board_slots\.[1-5]|pot_size|hero_seated|hero_seat|hero_chips|hero_cards|controls|role|to_call|scene|center_chip|pot_convention|street_contribution|position|seats\.[1-6]\.(?:displayed_stack|visible_wager|occupied|status|badge|dealer|small_blind|big_blind|acting|street_contribution|position))$/.test(key) || !record(entry)) continue;
      if (entry.status === "accepted") result[key] = { status: "accepted", reason: null };
      else if (entry.status === "unavailable" && Object.hasOwn(FIELD_REASONS, entry.reason)) result[key] = { status: "unavailable", reason: entry.reason };
    }
    return result;
  }

  function reasonFor(observation, field, fallback = "insufficient-context") {
    const state = observation?.fieldStatuses[field] || snapshot?.fieldStatuses[field];
    if (!observation && clearReason === "stale" && state?.reason !== "missing-capability") return FIELD_REASONS.stale;
    return FIELD_REASONS[state?.status === "unavailable" ? state.reason : fallback];
  }

  function text(id, value) {
    patchText(node(id), value);
  }

  function patchText(target, value) {
    if (target.textContent !== String(value)) target.textContent = String(value);
  }

  function attribute(target, key, value) {
    if (target.getAttribute(key) !== String(value)) target.setAttribute(key, String(value));
  }

  function data(target, key, value) {
    if (target.dataset[key] !== String(value)) target.dataset[key] = String(value);
  }

  function publishField(target, field, value, state, capture = null) {
    const seat = /^seats\.[1-6]\./.test(field) ? Number(field.split(".")[1]) : field.startsWith("selected_player.") ? selectedSeat : null;
    const signature = JSON.stringify([seat, value, state, capture]);
    const previous = renderedFields.get(field);
    let receipt = previous?.receipt;
    if (previous?.signature !== signature) {
      receipt = { field, seat, value, status: state, capture,
        published_at_unix_ms: Date.now(), published_at_monotonic_ms: performance.now() };
      renderedFields.set(field, { signature, receipt });
      renderReceipts.push(receipt);
      if (renderReceipts.length > RENDER_RECEIPT_LIMIT) { renderReceipts.shift(); droppedRenderReceipts += 1; }
    }
    data(target, "reading", state);
    data(target, "captureRef", JSON.stringify(capture));
    data(target, "capturedAtUnixMs", capture?.captured_at_unix_ms ?? "");
    data(target, "publishedAtUnixMs", receipt.published_at_unix_ms);
    data(target, "publishedAtMonotonicMs", receipt.published_at_monotonic_ms);
    return receipt;
  }

  function sourceAge(capture) {
    if (!capture) return null;
    const key = JSON.stringify(capture);
    const previous = sourceAges.get(key);
    const value = previous || { initial: Math.max(0, Date.now() - capture.captured_at_unix_ms), mono: performance.now(), age: 0 };
    value.age = Math.max(value.age, Date.now() - capture.captured_at_unix_ms, value.initial + performance.now() - value.mono);
    sourceAges.delete(key); sourceAges.set(key, value);
    if (sourceAges.size > 128) sourceAges.delete(sourceAges.keys().next().value);
    return value.age;
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

  async function readJson(response) {
    if (!response.body || !/\bapplication\/(?:[a-z0-9.-]+\+)?json\b/i.test(response.headers.get("content-type") || "")) throw new Error("unavailable");
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
  }

  async function getJson(path, controller) {
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(path, { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
      if (!response.ok) throw new Error("unavailable");
      return await readJson(response);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function startMatches() {
    return startRequest && startRequest.service === snapshot?.service && startRequest.control === snapshot?.captureControl?.id;
  }

  function stopMatches() {
    return stopRequest && stopRequest.service === snapshot?.service && (stopRequest.control !== null ?
      stopRequest.control === snapshot?.captureControl?.id && (stopRequest.session === null ||
        stopRequest.session === snapshot?.recording?.session) : stopRequest.session === snapshot?.recording?.session);
  }

  function canStartCapture() {
    const control = snapshot?.captureControl;
    return connected && !document.hidden && snapshot?.service && control?.enabled && control.canStart &&
      control.status === "available" && ["loading", "ready"].includes(snapshot.modelState) && snapshot.inferenceEnabled !== false &&
      !startController && !stopController && !(startMatches() && ["pending", "requested"].includes(startRequest.state));
  }

  function canStopCapture() {
    if (snapshot?.captureControl) return connected && !document.hidden && snapshot.service && snapshot.captureControl.enabled &&
      snapshot.captureControl.canStop && ["starting", "running"].includes(snapshot.captureControl.status) &&
      !stopController && !(stopMatches() && ["pending", "requested", "unavailable"].includes(stopRequest.state));
    return connected && !document.hidden && snapshot?.service && snapshot.recording?.session &&
      snapshot.recording.status === "capturing" && recordingFresh() &&
      recordingLease?.session === snapshot.recording.session && !retiredRecordings.has(snapshot.recording.session) &&
      !stopController && !(stopMatches() && ["requested", "unavailable"].includes(stopRequest.state));
  }

  function renderStopCapture() {
    const control = snapshot?.captureControl;
    node("start-capture").disabled = !canStartCapture();
    attribute(node("start-capture"), "aria-busy", !!(startMatches() && startRequest.state === "pending"));
    const startMessages = { pending: "Requesting monitor start.", requested: "Start accepted; waiting for the monitor receipt.",
      invalid: "Start request was rejected.", forbidden: "Start request origin was rejected.",
      unavailable: "Monitor start is no longer available.", failed: "Start not confirmed. No automatic retry." };
    text("start-capture-status", !connected ? "Monitor disconnected." : startMatches() ? startMessages[startRequest.state] :
      !snapshot?.service ? "Monitor service unavailable." : !control?.enabled ? "Manual start not configured." :
      ["disabled", "failed"].includes(snapshot.modelState) ? `Model ${snapshot.modelState}; start unavailable.` :
      control.message || ({ starting: "Starting monitor / validating source.", running: "Monitor running.",
        stopping: "Stopping monitor.", unavailable: "Monitor unavailable.", available: "Start only on request; model stays warm." })[control.status]);
    node("stop-capture").disabled = !canStopCapture();
    text("stop-capture", stopMatches() && stopRequest.state === "pending" ? "Stopping monitor..." : "Stop monitor");
    const messages = { pending: "Requesting monitor stop.", requested: "Stop requested; waiting for the session receipt.",
      unavailable: "Capture session is no longer available.", invalid: "Stop request was rejected.",
      forbidden: "Stop request origin was rejected.", failed: "Stop not confirmed. No automatic retry." };
    text("stop-capture-status", stopMatches() ? stopRequest.state === "requested" &&
      (control ? control.status === "available" : snapshot.recording.status !== "capturing") ?
      control ? "Monitor stopped; model stays warm." : `Capture session ${snapshot.recording.status}.` : messages[stopRequest.state] : "");
  }

  async function startCapture() {
    if (!canStartCapture()) return;
    const request = { service: snapshot.service, control: snapshot.captureControl.id, state: "pending" };
    startRequest = request;
    stopRequest = null;
    const version = lifecycle;
    const controller = new AbortController();
    startController = controller;
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    renderStopCapture();
    try {
      const response = await fetch("/api/capture/start", { method: "POST", mode: "same-origin", credentials: "omit",
        headers: { Accept: "application/json", "Content-Type": "application/json" }, cache: "no-store", redirect: "error",
        body: JSON.stringify({ service_instance_id: request.service, control_id: request.control }), signal: controller.signal });
      const result = await readJson(response);
      if (startRequest !== request || !startMatches() || !connected || version !== lifecycle) return;
      if (response.status === 202 && record(result) && Object.keys(result).length === 2 && result.ok === true &&
          controlId(result.control_id) && result.control_id !== request.control) request.state = "requested";
      else if (response.status === 409) request.state = "unavailable";
      else if (response.status === 400) request.state = "invalid";
      else if (response.status === 403) request.state = "forbidden";
      else request.state = "failed";
    } catch {
      if (startRequest === request && startMatches() && connected && version === lifecycle) request.state = "failed";
    } finally {
      window.clearTimeout(timeout);
      if (startController === controller) startController = null;
      renderStopCapture();
    }
  }

  async function stopCapture() {
    if (!canStopCapture()) return;
    const request = { service: snapshot.service, session: snapshot.recording?.status === "capturing" ? snapshot.recording.session : null,
      control: snapshot.captureControl?.id ?? null, state: "pending" };
    stopRequest = request;
    const version = lifecycle;
    const controller = new AbortController();
    stopController = controller;
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    renderStopCapture();
    try {
      const response = await fetch("/api/capture/stop", { method: "POST", mode: "same-origin", credentials: "omit",
        headers: { Accept: "application/json", "Content-Type": "application/json" }, cache: "no-store", redirect: "error",
        body: JSON.stringify({ session_id: request.session, service_instance_id: request.service,
          ...(request.control !== null ? { control_id: request.control } : {}) }), signal: controller.signal });
      const result = await readJson(response);
      if (stopRequest !== request || !stopMatches() || !connected || version !== lifecycle) {
        if (stopRequest === request) request.state = "failed";
        return;
      }
      if (response.status === 200 && record(result) && Object.keys(result).length === 1 && result.ok === true) {
        request.state = "requested";
        clearContext();
        clearVisual();
        clearRetained();
        clearExperimental();
        clearObservation();
      } else if (record(result) && Object.keys(result).length === 1 && response.status === 409 && result.error === "capture-session-unavailable") {
        request.state = "unavailable";
        disconnected();
      } else if (record(result) && Object.keys(result).length === 1 && response.status === 400 && result.error === "invalid-request") request.state = "invalid";
      else if (response.status === 403) request.state = "forbidden";
      else request.state = "failed";
    } catch {
      if (stopRequest === request && stopMatches() && connected && version === lifecycle) request.state = "failed";
    } finally {
      window.clearTimeout(timeout);
      if (stopController === controller) stopController = null;
      renderStopCapture();
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
    if (heroSeated !== true || phase === "unseated" || phase === "lobby") {
      for (const key of ["to_call", "hero_chips", "min_raise_to", "max_raise_to"]) amounts[key] = null;
    }
    if (role === "uncertain") for (const key of ["to_call", "min_raise_to", "max_raise_to"]) amounts[key] = null;
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
      phase, role, heroSeated, actionRequired, heroSeat: seatNumber(value.hero_seat) ? value.hero_seat : null,
      fieldStatuses: fieldStatuses(value.field_statuses), amountTexts: record(value.amount_texts) ? value.amount_texts : {},
      captureRef: normalizeCaptureRef(value.capture), fieldCaptures: normalizeFieldCaptures(value.field_captures),
      captureRefPresent: value.capture != null,
      actingSeat: seatNumber(value.acting_seat) ? value.acting_seat : null,
      hero: heroSeated === true ? hero : [], board, amounts, wagers, controls: labels,
      seats: SEAT_LOCATIONS.map((_, index) => ({ seat: index + 1, displayed_stack: null,
        visible_wager: wagers.find((entry) => entry.seat === index + 1)?.amount ?? null, street_contribution: null })),
      metrics: { rank: null, odds: null, draw: null, equity: null },
      partial: false,
      experimental: value.experimental === true,
      qualityApproved: value.quality_approved === false ? false : null,
      session: opaqueId(value.session_id) ? value.session_id : null,
      sourceId: sourceId(value.source_id) ? value.source_id : null,
      availableActions: Array.isArray(value.available_actions) && value.available_actions.length <= ACTIONS.length &&
        value.available_actions.every(action => ACTIONS.includes(action)) && new Set(value.available_actions).size === value.available_actions.length ?
        [...value.available_actions] : null
    };
  }

  function normalizeMetrics(value, observation) {
    const result = { rank: null, odds: null, draw: null, equity: null };
    if (!record(value)) return result;
    const hero = observation.heroSeated === true && observation.hero.length === 2;
    const odds = value.pot_odds;
    if (record(odds) && percentage(odds.required_equity_pct) && chipAmount(observation.amounts.pot_size) &&
        (observation.role === "observing" ? seatNumber(observation.actingSeat) && odds.seat === observation.actingSeat &&
          chipAmount(observation.amounts.acting_to_call) : hero && chipAmount(observation.amounts.to_call) &&
          (odds.seat === null || seatNumber(observation.heroSeat) && odds.seat === observation.heroSeat))) {
      result.odds = { seat: odds.seat, pct: odds.required_equity_pct };
    }
    if (hero) {
      result.rank = allowed(value.hand_rank, HAND_RANKS);
      result.equity = percentage(value.equity_pct) ? value.equity_pct : null;
      const draw = value.draw;
      if (["flop", "turn"].includes(observation.phase) && record(draw) && integer(draw.outs) && draw.outs <= 50 - observation.board.length &&
          percentage(draw.next_card_pct) && percentage(draw.by_river_pct) && draw.next_card_pct <= draw.by_river_pct) {
        result.draw = { outs: draw.outs, next: draw.next_card_pct, river: draw.by_river_pct };
      }
    }
    return result;
  }

  function normalizeAdvice(value, observation) {
    if (!record(value) || !observation?.analysisQualified || observation.role !== "your_turn" ||
        observation.heroSeated !== true || observation.actionRequired !== true || observation.hero.length !== 2 ||
        observation.phase === "showdown" || value.experimental !== true || value.quality_approved !== false ||
        value.session_id !== observation.session || value.source_id !== observation.sourceId ||
        value.generation !== observation.generation || value.epoch !== observation.epoch ||
        value.captured_at_unix_ms !== observation.captured || !integer(value.expires_at_unix_ms) ||
        value.expires_at_unix_ms > observation.expires || !integer(value.remaining_ms) || value.remaining_ms > observation.remaining ||
        !["fold", "check", "call", "raise", "all_in"].includes(value.action) || !chipAmount(value.amount) ||
        !Number.isFinite(value.ev) || value.ev < -4294967295 || value.ev > 8589934590 || !percentage(value.equity_pct) ||
        value.pot_odds_pct !== null && !percentage(value.pot_odds_pct) ||
        value.break_even_pct !== null && !percentage(value.break_even_pct) ||
        value.confidence !== null && !(Number.isFinite(value.confidence) && value.confidence >= 0 && value.confidence <= 1)) return null;
    const { pot_size: pot, to_call: call, hero_chips: stack, min_raise_to: min, max_raise_to: max } = observation.amounts;
    const control = observation.controls.get(value.action);
    const enabled = [...observation.controls].filter(([, state]) => state.presence === "present" && state.enabled === "enabled").map(([action]) => action);
    if (!observation.availableActions || !enabled.length || enabled.includes("bet") || observation.availableActions.length !== enabled.length ||
        !enabled.every(action => observation.availableActions.includes(action)) ||
        enabled.includes("check") && (call > 0 || enabled.includes("fold") || enabled.includes("call")) ||
        call === 0 && (enabled.includes("call") || enabled.includes("fold"))) return null;
    if (![pot, call, stack].every(chipAmount) || pot === 0 || stack === 0 || control?.presence !== "present" || control.enabled !== "enabled" ||
        value.action === "check" && (call !== 0 || value.amount !== 0) ||
        value.action === "fold" && (call === 0 || value.amount !== 0) ||
        value.action === "call" && (call === 0 || value.amount !== Math.min(call, stack)) ||
        value.action === "all_in" && (value.amount !== stack || stack > call) ||
        value.action === "raise" && (!chipAmount(min) || !chipAmount(max) || min === 0 || min > max || value.amount < min || value.amount > max)) return null;
    return { action: value.action, amount: value.amount, ev: value.ev, equity: value.equity_pct,
      odds: value.pot_odds_pct, breakEven: value.break_even_pct, confidence: value.confidence,
      captured: value.captured_at_unix_ms, expires: value.expires_at_unix_ms, remaining: value.remaining_ms };
  }

  function normalizePartialObservation(value, readoutOnly = false) {
    if (!record(value) || value.quality_approved !== false || value.experimental !== true ||
        !Array.isArray(value.board_slots) || value.board_slots.length !== 5 ||
        !Array.isArray(value.seats) || value.seats.length !== 6) return null;
    const seats = new Map();
    for (const entry of value.seats) {
      if (!record(entry) || !seatNumber(entry.seat) || seats.has(entry.seat)) return null;
      // Only the server's per-field projection can qualify a wager; no capability upgrade here.
      const sceneFields = ["occupied", "status", "badge", "dealer", "small_blind", "big_blind", "acting"];
      const verifiedScene = !readoutOnly && Array.isArray(entry.scene_fields) && entry.scene_fields.length <= 7 ?
        new Set(entry.scene_fields.filter((field) => sceneFields.includes(field))) : new Set();
      const scene = Object.fromEntries(sceneFields.map((field) => [field, null]));
      for (const field of ["occupied", "dealer", "small_blind", "big_blind", "acting"]) {
        if (verifiedScene.has(field) && typeof entry[field] === "boolean") scene[field] = entry[field];
      }
      if (verifiedScene.has("status") && ["active", "folded", "all_in", "sitting_out"].includes(entry.status)) scene.status = entry.status;
      if (verifiedScene.has("badge") && ["none", "fold", "check", "call", "bet", "raise", "all_in", "small_blind", "big_blind"].includes(entry.badge)) scene.badge = entry.badge;
      seats.set(entry.seat, { seat: entry.seat, displayed_stack: integer(entry.displayed_stack) ? entry.displayed_stack : null,
        visible_wager: !readoutOnly && entry.visible_wager_status === "accepted" && integer(entry.visible_wager) ? entry.visible_wager : null,
        displayed_stack_text: entry.displayed_stack_text, visible_wager_text: entry.visible_wager_text,
        occupantEpoch: integer(entry.occupant_epoch) ? entry.occupant_epoch : null,
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
    }
    const seated = !readoutOnly && typeof value.hero_seated === "boolean" ? value.hero_seated : null;
    const role = value.role === "observing" && seated === false ? "observing" : "uncertain";
    return {
      generation: integer(value.generation) ? value.generation : null,
      epoch: integer(value.epoch) ? value.epoch : null,
      expires: integer(value.expires_at_unix_ms) ? value.expires_at_unix_ms : null,
      remaining: integer(value.remaining_ms) ? value.remaining_ms : null,
      captured: integer(value.captured_at_unix_ms) && value.captured_at_unix_ms > 0 ? value.captured_at_unix_ms : null,
      phase, role, heroSeated: seated, actionRequired: null, heroSeat: null,
      fieldStatuses: fieldStatuses(value.field_statuses), amountTexts: { pot_size: value.pot_size_text },
      captureRef: normalizeCaptureRef(value.capture), fieldCaptures: normalizeFieldCaptures(value.field_captures),
      captureRefPresent: value.capture != null,
      actingSeat: [...seats.values()].filter((entry) => entry.acting === true).length === 1 ?
        [...seats.values()].find((entry) => entry.acting === true).seat : null,
      hero: [], board, boardCount, amounts: { pot_size: integer(value.pot_size) ? value.pot_size : null,
        to_call: null, acting_to_call: null, hero_chips: null, min_raise_to: null, max_raise_to: null },
      seats: SEAT_LOCATIONS.map((_, index) => seats.get(index + 1)), wagers: [], controls: new Map(),
      metrics: { rank: null, odds: null, draw: null, equity: null }, partial: true, experimental: true
    };
  }

  function normalizeCaptureRef(value, parentOnly = false) {
    if (!record(value) || !opaqueId(value.service_instance_id) || !opaqueId(value.session_id) || !sourceId(value.source_id) ||
        !["epoch", "sequence", "captured_at_unix_ms", "width", "height"].every(key => integer(value[key]) && value[key] > 0) ||
        !integer(value.captured_at_ms) || typeof value.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.sha256)) return null;
    const result = Object.fromEntries(["service_instance_id", "session_id", "source_id", "epoch", "sequence",
      "captured_at_ms", "captured_at_unix_ms", "sha256", "width", "height"].map(key => [key, value[key]]));
    if (opaqueId(value.capture_session_id)) result.capture_session_id = value.capture_session_id;
    if (integer(value.native_source_id) || opaqueId(value.native_source_id)) result.native_source_id = value.native_source_id;
    if (integer(value.generation)) result.generation = value.generation;
    if (value.parent_capture != null) {
      const parent = parentOnly ? null : normalizeCaptureRef(value.parent_capture, true);
      const popup = value.popup_window;
      if (!parent || value.non_atomic !== true || !integer(value.popup_index) || value.popup_index > 3 || !record(popup) ||
          ["service_instance_id", "session_id", "source_id", "epoch", "capture_session_id"].some(key => parent[key] !== result[key]) ||
          !["hwnd", "owner_hwnd", "root_owner_hwnd"].every(key => opaqueId(popup[key])) ||
          !integer(popup.process_id) || popup.process_id === 0 || typeof popup.window_class !== "string" || popup.window_class.length > 128) return null;
      result.parent_capture = parent;
      result.popup_index = value.popup_index;
      result.non_atomic = true;
      result.popup_window = Object.fromEntries(["hwnd", "owner_hwnd", "root_owner_hwnd", "process_id", "window_class"].map(key => [key, popup[key]]));
      if (Array.isArray(popup.relative_bounds) && popup.relative_bounds.length === 4 && popup.relative_bounds.every(Number.isSafeInteger)) {
        result.popup_window.relative_bounds = [...popup.relative_bounds];
      }
    }
    return result;
  }

  function normalizeFieldCaptures(value) {
    if (!record(value)) return {};
    return Object.fromEntries(Object.entries(value).slice(0, 64).filter(([key]) =>
      /^(?:pot_size|board_slots\.[1-5]|seats\.[1-6]\.(?:displayed_stack|visible_wager|badge|occupied|status|dealer|small_blind|big_blind|acting))$/.test(key))
      .map(([key, capture]) => [key, normalizeCaptureRef(capture)]));
  }

  function captureInScope(capture, value = snapshot) {
    return !!capture && !capture.parent_capture && !!value && capture.service_instance_id === value.service && capture.session_id === value.session &&
      capture.source_id === value.capture.sourceId && capture.epoch === value.capture.epoch &&
      capture.width === value.capture.width && capture.height === value.capture.height &&
      (!capture.capture_session_id || capture.capture_session_id === value.recording?.session);
  }

  function originalFor(observation, field) {
    if (!observation) return null;
    if (Object.hasOwn(observation.fieldCaptures, field)) {
      const fieldCapture = observation.fieldCaptures[field];
      return captureInScope(fieldCapture) && fieldCapture.captured_at_unix_ms <= observation.captured ? fieldCapture : null;
    }
    const capture = observation.captureRef;
    if (capture && captureInScope(capture) && capture.captured_at_unix_ms <= observation.captured) return capture;
    // Legacy numeric tickets do not contain a PNG/sequence crosswalk. Never borrow another lane's capture.
    return { complete: false, service_instance_id: snapshot?.service ?? null, session_id: snapshot?.session ?? null,
      source_id: snapshot?.capture.sourceId ?? null, epoch: observation.epoch, generation: observation.generation,
      captured_at_unix_ms: observation.captured };
  }

  function normalizeProfile(value, entry, capture, tableId) {
    const original = normalizeCaptureRef(value?.capture);
    const scope = original?.parent_capture || original;
    if (!record(value) || value.source !== "client_profile_tooltip" || value.owner !== entry.identity ||
        value.seat !== entry.seat || value.occupant_epoch !== entry.occupantEpoch || !entry.identity || tableId === null ||
        entry.occupancy !== "occupied" || entry.continuity !== "confirmed" || !original ||
        ["service_instance_id", "session_id", "source_id", "epoch", "width", "height", "capture_session_id"].some(key => scope[key] !== capture[key]) ||
        scope.sequence > capture.sequence || scope.captured_at_unix_ms > capture.captured_at_unix_ms ||
        original.captured_at_unix_ms > Date.now() || !original.parent_capture && original.captured_at_unix_ms > capture.captured_at_unix_ms ||
        value.captured_at_unix_ms !== original.captured_at_unix_ms ||
        tableId !== null && value.table_context_id !== tableId ||
        !["confirmed", "provisional", "last_observed"].includes(value.status) || !record(value.metrics)) return null;
    const metrics = {};
    const labelPatterns = { vpip: /^VPIP$/i, pfr: /^PFR$/i, three_bet: /^3[ -]?BET$/i, c_bet: /^(?:(?:Flop|Turn|River)\s+)?C[ -]?BET\b/i };
    for (const [key, fallback] of PROFILE_METRICS) {
      const field = value.metrics[key];
      if (!record(field)) { metrics[key] = { label: fallback, literal: "-", status: "missing" }; continue; }
      const label = safeLabel(field.label, fallback, 64);
      const validLabel = typeof field.label === "string" && labelPatterns[key].test(label);
      const literal = typeof field.literal === "string" && field.literal.length <= 32 ? field.literal.trim() : null;
      const supported = ["confirmed", "provisional", "accepted"].includes(field.status);
      const valid = validLabel && supported && literal !== null && /^\d{1,3}(?:\.\d{1,6})?\s*%$/.test(literal) &&
        percentage(field.percent) && Number(literal.replace(/\s*%$/, "")) === field.percent;
      metrics[key] = { label: validLabel ? label : fallback, literal: valid ? literal : "-", status: valid ? field.status :
        allowed(field.status, ["missing", "dash", "unreadable", "invalid", "unknown", "partial"], "unknown") };
    }
    return { metrics, capture: original, status: value.status, provisional: value.provisional === true || value.human_reviewed === false,
      sample: integer(value.sample_size) ? value.sample_size : null,
      scope: value.scope === null ? null : safeLabel(value.scope, null, 160),
      evidenceId: typeof value.evidence_id === "string" && /^[a-f0-9]{64}$/.test(value.evidence_id) ? value.evidence_id : null };
  }

  function normalizeTableContext(value) {
    const capture = normalizeCaptureRef(value?.capture);
    if (!record(value) || value.schema_version !== 1 || !capture || capture.parent_capture || !integer(value.expires_at_unix_ms) ||
        value.expires_at_unix_ms <= capture.captured_at_unix_ms || value.expires_at_unix_ms > capture.captured_at_unix_ms + MAX_LEASE_MS ||
        !ROLES.includes(value.role) || value.hero_seat !== null && !seatNumber(value.hero_seat) ||
        !Array.isArray(value.seats) || value.seats.length !== 6) return null;
    const seats = new Map();
    const tableId = opaqueId(value.table_context_id) ? value.table_context_id : null;
    for (const raw of value.seats) {
      if (!record(raw) || !seatNumber(raw.seat) || seats.has(raw.seat) || !["occupied", "empty", "unknown"].includes(raw.occupancy) ||
          !integer(raw.occupant_epoch) || !["confirmed", "uncertain"].includes(raw.continuity) ||
          !["provisional", "confirmed", "unknown"].includes(raw.status) || typeof raw.reason !== "string" ||
          raw.identity !== null && (typeof raw.identity !== "string" || !raw.identity.trim() || raw.identity.length > 96 ||
            safeLabel(raw.identity, null, 96) !== raw.identity)) return null;
      const entry = { seat: raw.seat, occupancy: raw.status === "unknown" ? "unknown" : raw.occupancy,
        identity: raw.occupancy === "occupied" && raw.continuity === "confirmed" && raw.status !== "unknown" ? raw.identity : null,
        occupantEpoch: raw.occupant_epoch, continuity: raw.continuity, status: raw.status,
        reason: safeLabel(raw.reason, "Unknown", 160), stats: null };
      entry.stats = normalizeProfile(raw.stats, entry, capture, tableId);
      seats.set(entry.seat, entry);
    }
    const owners = new Set();
    const duplicates = new Set();
    for (const entry of seats.values()) if (entry.identity) {
      if (owners.has(entry.identity)) duplicates.add(entry.identity);
      owners.add(entry.identity);
    }
    for (const entry of seats.values()) if (duplicates.has(entry.identity)) {
      entry.identity = null; entry.stats = null; entry.continuity = "uncertain"; entry.reason = "Duplicate identity / owner uncertain";
    }
    const roleEvidence = value.evidence?.role;
    const roleCapture = normalizeCaptureRef(roleEvidence?.capture);
    const origins = { observing: "observer_controls", seated_waiting: "self_player", your_turn: "own_action_controls" };
    const roleQualified = record(roleEvidence) && ["confirmed", "provisional"].includes(roleEvidence.status) && roleCapture &&
      JSON.stringify(roleCapture) === JSON.stringify(capture) && roleEvidence.origin === origins[value.role] &&
      roleEvidence.hero_seat === value.hero_seat && (value.role === "observing" ? value.hero_seat === null : seatNumber(value.hero_seat));
    const role = roleQualified ? value.role : "uncertain";
    return { capture, expires: value.expires_at_unix_ms, tableId, role, provisional: value.provisional === true || value.human_reviewed === false,
      roleStatus: roleQualified ? roleEvidence.status : "unknown", heroSeat: roleQualified ? value.hero_seat : null,
      seats: SEAT_LOCATIONS.map((_, index) => seats.get(index + 1)) };
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

  function normalizeExperimental(value) {
    const keys = ["version", "diagnostic_only", "quality_approved", "training", "geometry_status", "human_review",
      "fitted_floor", "seat", "kind", "generation", "epoch", "captured_at_unix_ms", "expires_at_unix_ms", "remaining_ms",
      "glyph_scores", "scene", "donor_pass", "inherited_cutoff", "numeric_text", "reason"];
    if (!record(value) || value.version !== 1 || value.diagnostic_only !== true || value.quality_approved !== false ||
        Object.keys(value).some(key => !keys.includes(key)) || keys.some(key => !Object.hasOwn(value, key)) ||
        value.training !== "unvalidated" || value.geometry_status !== "DRAFT" || value.human_review !== "PENDING" ||
        value.fitted_floor !== null || !integer(value.seat) || value.seat < 1 || value.seat > 6 ||
        !["wager", "scene"].includes(value.kind) || !integer(value.generation) || !integer(value.epoch) ||
        !integer(value.captured_at_unix_ms) || !integer(value.expires_at_unix_ms) || !integer(value.remaining_ms) ||
        !Array.isArray(value.glyph_scores) || value.glyph_scores.length > 8 || !Array.isArray(value.scene) || value.scene.length > 7) return null;
    const probability = number => typeof number === "number" && Number.isFinite(number) && number >= 0 && number <= 1;
    if (value.kind === "wager") {
      if (value.donor_pass !== "p5_seat_1_stack" || !probability(value.inherited_cutoff) || value.inherited_cutoff < .8 || value.scene.length) return null;
      if (value.numeric_text !== null && (typeof value.numeric_text !== "string" || value.numeric_text.length > 8 ||
          !/^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?$/.test(value.numeric_text) ||
          value.glyph_scores.length !== value.numeric_text.length || value.glyph_scores.some(score => !probability(score) || score < value.inherited_cutoff))) return null;
      if (value.numeric_text === null && value.glyph_scores.length) return null;
      if (value.numeric_text !== null && Number(value.numeric_text.replaceAll(",", "")) * 100 > 4294967295) return null;
    } else {
      if (value.donor_pass !== null || value.inherited_cutoff !== null || value.numeric_text !== null || value.glyph_scores.length || value.scene.length !== 7) return null;
      const seen = new Set();
      for (const item of value.scene) {
        if (!record(item) || !Object.hasOwn(EXPERIMENTAL_SCENE, item.field) || seen.has(item.field) || item.fitted_floor !== null ||
            item.guess !== null && !EXPERIMENTAL_SCENE[item.field].includes(item.guess) || item.score !== null && !probability(item.score)) return null;
        seen.add(item.field);
      }
    }
    return { epoch: value.epoch, generation: value.generation, captured: value.captured_at_unix_ms,
      expires: value.expires_at_unix_ms, remaining: value.remaining_ms, seat: value.seat, kind: value.kind,
      text: value.numeric_text, cutoff: value.inherited_cutoff, scores: [...value.glyph_scores],
      scene: value.scene.map(item => ({ field: item.field, guess: item.guess, score: item.score })),
      reason: ["unapproved-capability", "empty-segmentation", "segmentation-overflow", "missing-segments", "below-floor", "invalid-answer", "invalid-amount"].includes(value.reason) ? value.reason : "invalid-answer" };
  }

  function normalizeSnapshot(value) {
    if (!record(value) || value.schema_version !== 1 || !opaqueId(value.session_id) || !integer(value.event_seq)) return null;
    if (!["idle", "live"].includes(value.source)) return null;
    const server = value.server;
    const capture = value.capture;
    if (!record(server) || !MODEL_STATES.includes(server.model_state) || typeof server.quality_gate !== "string" || typeof server.advice_ready !== "boolean") return null;
    if (!record(capture) || !CAPTURE_STATES.includes(capture.state) || typeof capture.fresh_capture !== "boolean") return null;
    if (!integer(capture.frames) || typeof server.inference_busy !== "boolean" || typeof server.temperature_calibration_loaded !== "boolean") return null;
    if (!["UI_READY", "COLLECTOR_READY"].includes(value.readiness)) return null;
    const recording = normalizeRecording(value.capture_session);
    if (value.capture_session != null && !recording) return null;
    const startup = value.automatic_startup;
    if (startup != null && (!record(startup) || typeof startup.enabled !== "boolean" ||
         startup.enabled && !Object.hasOwn(AUTOMATIC_LABELS, startup.status))) return null;
    const control = value.capture_control;
    if (control != null && (!record(control) || !controlId(control.control_id) || typeof control.enabled !== "boolean" ||
        !["available", "starting", "running", "stopping", "unavailable"].includes(control.status) ||
        typeof control.can_start !== "boolean" || typeof control.can_stop !== "boolean")) return null;
    const sourceTerminalBoundary = ["source-unavailable", "source-changed", "capture-failed", "inference-failed",
      "model-not-ready", "publication-failed", "feed-failed", "invalid-feed-record", "recorder-failure"].includes(value.message);
    const result = {
      session: value.session_id, sequence: value.event_seq, source: value.source,
      capture: {
        state: capture.state, fresh: capture.fresh_capture,
        frames: capture.frames,
        epoch: integer(capture.epoch) ? capture.epoch : null,
        generation: integer(capture.generation) ? capture.generation : null,
        sourceId: sourceId(capture.source_id) ? capture.source_id : null,
        width: integer(capture.width) && capture.width > 0 ? capture.width : null,
        height: integer(capture.height) && capture.height > 0 ? capture.height : null,
        transient: ["capture-not-fresh", "capture-heartbeat-expired"].includes(value.message),
        heartbeat: integer(capture.last_heartbeat_unix_ms) && capture.last_heartbeat_unix_ms > 0 ? capture.last_heartbeat_unix_ms : null
      },
      service: opaqueId(server.instance_id) ? server.instance_id : null,
      sourceBoundary: sourceTerminalBoundary || value.message === "capture-identity-or-epoch-changed",
      sourceTerminalBoundary,
      fieldsChanged: ["source-region-changed", "frame-changed", "observation-invalidated"].includes(value.message),
      modelState: server.model_state, inferenceBusy: server.inference_busy,
      qualityGate: allowed(server.quality_gate, ["failed", "passed", "unknown"], "unknown"),
      inferenceEnabled: typeof server.inference_enabled === "boolean" ? server.inference_enabled : null,
      experimentalEnabled: server.experimental_bet_action === true,
      fieldStatuses: fieldStatuses(value.field_statuses),
      recording,
      captureControl: control ? { id: control.control_id, enabled: control.enabled, status: control.status,
        canStart: control.can_start, canStop: control.can_stop, message: safeLabel(control.message, null, 160) } : null,
      automaticStartup: startup?.enabled ? { status: startup.status,
        stopReason: allowed(startup.stop_reason, ["automatic-discovery-timeout", "automatic-startup-failed",
          "practice-target-ambiguous", "practice-profile-invalid", "window-list-failed", "operator-stop",
          "duration-limit", "frame-limit", "model-not-ready", "table-activity-unconfirmed"], null) } : null,
      observation: value.partial_observation != null ? normalizePartialObservation(value.partial_observation,
        automaticPolicy(recording?.sourcePolicy) && recording.activityState !== "active") : normalizeObservation(value.observation),
      history: normalizeHistory(value.history),
      experimental: value.experimental_candidates == null ? null : normalizeExperimental(value.experimental_candidates),
      visual: normalizeVisual(value.visual_observation),
      numeric: normalizeNumeric(value.numeric_observation),
      tableContext: normalizeTableContext(value.table_context)
    };
    const observation = result.observation;
    if (observation && !observation.partial) {
      observation.analysisQualified = !!(result.service && result.source === "live" && result.modelState === "ready" &&
        result.inferenceEnabled !== false && observation.experimental &&
        observation.qualityApproved === false && observation.role !== "uncertain" && observation.session === result.session && observation.sourceId &&
        observation.sourceId === result.capture.sourceId && observation.generation === result.capture.generation &&
        observation.epoch === result.capture.epoch && result.capture.width !== null && result.capture.height !== null &&
        Object.hasOwn({ preflop: 0, flop: 3, turn: 4, river: 5, showdown: 5 }, observation.phase) &&
        observation.board.length === { preflop: 0, flop: 3, turn: 4, river: 5, showdown: 5 }[observation.phase] &&
        [0, 2].includes(observation.hero.length));
      if (observation.analysisQualified) observation.metrics = normalizeMetrics(value.observation.metrics, observation);
    }
    result.advice = server.advice_ready ? normalizeAdvice(value.advice, observation) : null;
    return result;
  }

  function renderCards(id, cards, slots, label) {
    const signature = JSON.stringify([cards, slots, label]);
    if (node(id).dataset.cardsSignature === signature) return;
    data(node(id), "cardsSignature", signature);
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

  function normalizeNumeric(value) {
    if (!record(value) || value.schema_version !== 1 || value.source !== "cpu-visible-numeric" ||
        value.provisional !== true || value.quality_approved !== false || !Array.isArray(value.seats) || value.seats.length !== 6) return null;
    const capture = normalizeCaptureRef(value.capture);
    if (!capture || !integer(value.expires_at_unix_ms) || value.expires_at_unix_ms <= capture.captured_at_unix_ms ||
        value.expires_at_unix_ms > capture.captured_at_unix_ms + 1500) return null;
    const field = raw => {
      if (!record(raw) || !["provisional", "unknown", "occluded", "empty"].includes(raw.status)) return null;
      const ref = normalizeCaptureRef(raw.capture);
      if (!ref || ["service_instance_id", "session_id", "source_id", "epoch", "sequence", "width", "height", "sha256", "captured_at_unix_ms", "captured_at_ms"]
          .some(key => ref[key] !== capture[key])) return null;
      if (raw.status !== "provisional") return raw.value === null && raw.literal === null ? { status: raw.status, value: null, literal: null, capture: ref } : null;
      if (typeof raw.literal !== "string" || !/^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?$/.test(raw.literal) || !integer(raw.value)) return null;
      const [whole, fraction = ""] = raw.literal.split(".");
      if (Number(whole) * 100 + Number(fraction.padEnd(2, "0")) !== raw.value) return null;
      return { status: "provisional", value: raw.value, literal: raw.literal, capture: ref };
    };
    const pot = field(value.pot), seats = [];
    if (!pot) return null;
    for (const [index, row] of value.seats.entries()) {
      if (!record(row) || row.seat !== index + 1) return null;
      const stack = field(row.stack), wager = field(row.wager);
      if (!stack || !wager) return null;
      seats.push({ seat: row.seat, stack, wager });
    }
    return { capture, captured: capture.captured_at_unix_ms, expires: value.expires_at_unix_ms, pot, seats };
  }

  function admitNumeric(value, roundTripMs) {
    const numeric = value.numeric, now = Date.now();
    const binding = numeric ? [value.service, value.session, value.recording?.session, value.capture.sourceId, value.capture.epoch].join("|") : null;
    if (!numeric || value.recording?.status !== "capturing" || !captureHealthy() || !captureInScope(numeric.capture, value) ||
        numeric.captured > now || numeric.expires - roundTripMs <= now ||
        tableBoundaryCapture !== null && numeric.captured < tableBoundaryCapture ||
        numericFloor?.binding === binding && (numeric.capture.sequence < numericFloor.sequence ||
          numeric.capture.sequence === numericFloor.sequence && (numeric.captured !== numericFloor.captured || numeric.capture.sha256 !== numericFloor.sha || performance.now() >= numericFloor.deadline))) {
      numericLease = null; return;
    }
    const same = numericFloor?.binding === binding && numericFloor.sequence === numeric.capture.sequence;
    const next = [numeric.pot, ...numeric.seats.flatMap(row => [row.stack, row.wager])];
    if (same) {
      for (const [index, item] of next.entries()) if (item.status === "provisional" &&
          (!numericFloor.eligible[index] || numericFloor.literals[index] !== item.literal)) {
        item.status = "unknown"; item.value = item.literal = null;
      }
    }
    const deadline = performance.now() + Math.min(1500, numeric.expires - now - roundTripMs);
    numericLease = { value: numeric, binding, deadline: same ? Math.min(numericFloor.deadline, deadline) : deadline };
    numericFloor = { binding, sequence: numeric.capture.sequence, captured: numeric.captured, sha: numeric.capture.sha256,
      deadline: numericLease.deadline, eligible: next.map(item => item.status === "provisional"), literals: next.map(item => item.literal) };
    for (const [path, item] of [["pot_size", numeric.pot], ...numeric.seats.map(row => [`seats.${row.seat}.displayed_stack`, row.stack])]) {
      if (item.status === "empty") { retainedNumbers.delete(path); continue; }
      const fence = path === "pot_size" ? null : occupantFences.get(Number(path.split(".")[1]));
      if (item.status !== "provisional" || !retentionAllowed() || fence?.empty || fence && numeric.captured < fence.captured) continue;
      const previous = retainedNumbers.get(path);
      if (previous && previous.captured >= numeric.captured) continue;
      const age = Math.max(0, now - numeric.captured);
      retainedNumbers.set(path, { value: item.value, literal: item.literal, captured: numeric.captured, capture: item.capture,
        key: `numeric:${binding}:${numeric.capture.sequence}:${path}`, mono: performance.now(), sourceAge: age, age, changed: false });
    }
    for (const [path, item] of [["pot_size", numeric.pot], ...numeric.seats.flatMap(row => [
      [`seats.${row.seat}.displayed_stack`, row.stack], [`seats.${row.seat}.visible_wager`, row.wager]])]) {
      const previous = numericSupersession.get(path);
      if (["provisional", "empty"].includes(item.status) && (!previous || numeric.captured > previous.captured_at_unix_ms)) numericSupersession.set(path, item.capture);
    }
  }

  function newestNumeric(item, native, nativeCapture, fence = null) {
    return item?.status === "provisional" && (!fence || !fence.empty && item.capture.captured_at_unix_ms >= fence.captured) &&
      (!integer(native) || !nativeCapture || item.capture.captured_at_unix_ms >= nativeCapture.captured_at_unix_ms) ? item : null;
  }

  function numericCleared(item, nativeCapture, fence = null) {
    return item?.status === "empty" && (!fence || !fence.empty && item.capture.captured_at_unix_ms >= fence.captured) &&
      (!nativeCapture || item.capture.captured_at_unix_ms >= nativeCapture.captured_at_unix_ms);
  }

  function numericSupersedes(path, capture) {
    const newer = numericSupersession.get(path);
    return newer && (!capture || newer.captured_at_unix_ms >= capture.captured_at_unix_ms);
  }

  function normalizeVisual(value) {
    if (!record(value) || value.schema_version !== 1 || value.provisional !== true ||
        value.quality_approved !== false || value.human_reviewed !== false ||
        !opaqueId(value.session_id) || !opaqueId(value.service_instance_id) || !sourceId(value.source_id) ||
        !["epoch", "sequence", "captured_at_unix_ms", "expires_at_unix_ms", "width", "height"].every((k) => integer(value[k]) && value[k] > 0) ||
        !integer(value.captured_at_ms) || !record(value.actions.capture) ||
        value.actions.capture.session_id !== value.session_id || value.actions.capture.source_id !== value.source_id ||
        value.actions.capture.epoch !== value.epoch || value.actions.capture.sequence !== value.sequence ||
        value.actions.capture.captured_at_ms !== value.captured_at_ms ||
        value.expires_at_unix_ms !== value.captured_at_unix_ms + 1500 ||
        typeof value.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.sha256) ||
        !record(value.board) || !record(value.actions) || !Array.isArray(value.actions.seats) || value.actions.seats.length !== 6) return null;
    const raw = value.board.candidate_cards;
    const cards = Array.isArray(raw) && [0, 3, 4, 5].includes(raw.length) && new Set(raw).size === raw.length &&
      raw.every((c) => typeof c === "string" && /^[23456789TJQKA][shdc]$/.test(c)) ?
      raw.map((c) => ({ rank: c[0], suit: c[1] })) : null;
    const sameSource = capture => capture && ["service_instance_id", "session_id", "source_id", "epoch", "width", "height"].every(key => capture[key] === value[key]) &&
      capture.sequence <= value.sequence && capture.captured_at_unix_ms <= value.captured_at_unix_ms;
    const normalizeSlots = (rows, historical = false) => {
      if (!Array.isArray(rows) || rows.length !== 5) return null;
      const result = [];
      for (const [index, row] of rows.entries()) {
        if (historical && row?.slot === index + 1 && row.card === null && row.status === "unknown" && row.capture === null) {
          result.push({ card: null, capture: null, status: "unknown", historical: true });
          continue;
        }
        const capture = normalizeCaptureRef(row?.capture);
        const card = typeof row?.card === "string" && /^[23456789TJQKA][shdc]$/.test(row.card) ? { rank: row.card[0], suit: row.card[1] } : null;
        const statuses = historical ? ["last_seen", "provisional", "empty", "unknown", "occluded"] : ["provisional", "empty", "unknown", "occluded"];
        if (!record(row) || row.slot !== index + 1 || !statuses.includes(row.status) ||
            !sameSource(capture) || !historical && (capture.sequence !== value.sequence || capture.captured_at_unix_ms !== value.captured_at_unix_ms) ||
            row.card !== null && !card || ["provisional", "last_seen"].includes(row.status) && !card ||
            !["provisional", "last_seen"].includes(row.status) && card) return null;
        result.push({ card, capture, status: row.status, historical });
      }
      const known = result.filter(row => row.card).map(row => row.card.rank + row.card.suit);
      return new Set(known).size === known.length ? result : null;
    };
    const boardSlots = value.board_slots == null ? null : normalizeSlots(value.board_slots);
    const last = value.board.last_seen;
    const lastBoard = record(last) && last.status === "last_seen" && last.quality_approved === false && last.provisional === true ? normalizeSlots(last.board_slots, true) : null;
    const revealed = value.revealed_cards;
    let revealedSeats = [];
    if (record(revealed) && revealed.source === "visible_seat_cards" && revealed.quality_approved === false &&
        ["unknown", "showdown"].includes(revealed.phase) && Array.isArray(revealed.seats) && revealed.seats.length === 6 &&
        sameSource(normalizeCaptureRef(revealed.capture))) {
      const claimed = new Set();
      for (const [index, row] of revealed.seats.entries()) {
        if (!record(row) || row.seat !== index + 1 || !integer(row.visible_face_count) || row.visible_face_count > 2 || !Array.isArray(row.readings) || row.readings.length > 2) { revealedSeats = []; break; }
        const readings = [];
        for (const reading of row.readings) {
          const capture = normalizeCaptureRef(reading?.capture);
          const card = typeof reading?.card === "string" && /^[23456789TJQKA][shdc]$/.test(reading.card) ? reading.card : null;
          if (!sameSource(capture) || capture.sequence !== value.sequence || capture.captured_at_unix_ms !== value.captured_at_unix_ms ||
              !["provisional", "unknown", "occluded"].includes(reading?.status) || card && reading.status !== "provisional") { readings.length = 0; break; }
          const duplicate = card && (claimed.has(card) || boardSlots?.some(s => s.card && s.card.rank + s.card.suit === card));
          if (card && !duplicate) claimed.add(card);
          readings.push({ card: duplicate ? null : card, capture });
        }
        revealedSeats.push({ seat: row.seat, faceCount: row.visible_face_count, readings,
          identity: row.association_status === "confirmed" ? safeLabel(row.identity, null, 96) : null,
          epoch: integer(row.occupant_epoch) ? row.occupant_epoch : null });
      }
    }
    const seen = new Set();
    const seats = [];
    for (const seat of value.actions.seats) {
      if (!record(seat) || !integer(seat.seat) || seat.seat < 1 || seat.seat > 6 || seen.has(seat.seat)) return null;
      seen.add(seat.seat);
      for (const field of [seat.badge, seat.visible_wager]) {
        const source = field?.source_capture;
        if (!record(field) || !record(source) || source.session_id !== value.session_id ||
            source.source_id !== value.source_id || source.epoch !== value.epoch || source.sequence !== value.sequence ||
            source.captured_at_ms !== value.captured_at_ms || field.expires_at_ms !== value.captured_at_ms + 1500 ||
            field.human_reviewed !== false || !["unknown", "clear", "provisional"].includes(field.status)) return null;
      }
      const badge = seat.badge.status === "provisional" && record(seat.badge.value) && ACTIONS.includes(seat.badge.value.value) ? seat.badge.value.value : null;
      const wager = seat.visible_wager.status === "provisional" && record(seat.visible_wager.value) && typeof seat.visible_wager.value.literal === "string" &&
        /^\d{1,9}(?:\.\d{1,2})?$/.test(seat.visible_wager.value.literal) ? seat.visible_wager.value.literal : null;
      seats.push({ seat: seat.seat, badge, wager, absent: seat.badge.status === "clear" });
    }
    return { session: value.session_id, service: value.service_instance_id, sourceId: value.source_id,
      epoch: value.epoch, sequence: value.sequence, captured: value.captured_at_unix_ms,
      captureRef: normalizeCaptureRef(value.capture) || normalizeCaptureRef(value),
      expires: value.expires_at_unix_ms, width: value.width, height: value.height, sha: value.sha256,
      cards, boardSlots, lastBoard, revealedSeats, currentUncertain: value.current_uncertain === true,
      boardGeneration: integer(value.board.board_generation) ? value.board.board_generation : null,
      reason: safeLabel(value.board.reason, "Unknown", 80), seats,
      sightings: Array.isArray(value.sightings) ? value.sightings.slice(-30).filter((s) => record(s) &&
        integer(s.seat) && s.seat >= 1 && s.seat <= 6 && ACTIONS.includes(s.action)).map((s) =>
        ({ seat: s.seat, action: s.action, order: safeLabel(s.order_status, "unknown", 40) })) : [] };
  }

  function clearVisual() {
    visualLease = null;
    node("visual-panel").hidden = true;
  }

  function admitVisual(value, roundTripMs) {
    const visual = value.visual;
    const binding = visual ? [visual.service, visual.session, visual.sourceId, visual.epoch].join("|") : null;
    const now = Date.now();
    if (!visual || value.recording?.status !== "capturing" || !captureHealthy() ||
        visual.service !== value.service || visual.session !== value.session || visual.sourceId !== value.capture.sourceId ||
        visual.epoch !== value.capture.epoch || visual.width !== value.capture.width || visual.height !== value.capture.height ||
        visual.captured > now ||
        visualFloor?.binding === binding && (visual.sequence < visualFloor.sequence ||
          visual.sequence === visualFloor.sequence && visual.captured !== visualFloor.captured)) { clearVisual(); return; }
    if (historicalVisual && visual.boardGeneration !== null && historicalVisual.boardGeneration !== null && visual.boardGeneration !== historicalVisual.boardGeneration ||
        !visual.currentUncertain && visual.boardSlots?.every(row => row.status === "empty")) historicalVisual = null;
    if (visual.lastBoard && (tableBoundaryCapture === null || visual.lastBoard.every(row => !row.card || row.capture.captured_at_unix_ms >= tableBoundaryCapture))) historicalVisual = visual;
    if (visual.currentUncertain || visual.expires - roundTripMs <= now) { clearVisual(); return; }
    const same = visualLease?.binding === binding && visualLease.value.sequence === visual.sequence;
    if (visualFloor?.binding === binding && visual.sequence === visualFloor.sequence && !same) { clearVisual(); return; }
    visualFloor = { binding, sequence: visual.sequence, captured: visual.captured };
    visualLease = { value: visual, binding, deadline: Math.min(same ? visualLease.deadline : Infinity,
      performance.now() + visual.expires - now - roundTripMs) };
    node("visual-panel").hidden = false;
    renderCards("visual-board", visual.cards || [], visual.cards?.length || 0, "Provisional board");
    text("visual-board-reason", visual.cards === null ? visual.reason : visual.cards.length === 0 ?
      "No card faces in board slots / not a verified hand boundary" : "Provisional pixel match / unvalidated");
    for (const seat of visual.seats) {
      const slot = tableNodes.visual[seat.seat - 1];
      patchText(slot.badge, seat.badge ? seat.badge.replaceAll("_", " ").toUpperCase() : seat.absent ? "No action badge / provisional" : "Badge unknown");
      patchText(slot.wager, `Visible wager: ${seat.wager ?? "unknown"}`);
    }
    text("visual-source", `Original capture ${new Date(visual.captured).toISOString()} / PNG SHA256 ${visual.sha.slice(0, 16)} / unvalidated`);
    node("visual-sightings").replaceChildren(...visual.sightings.slice().reverse().map((s) =>
      make("li", "", `Seat ${s.seat}: ${s.action.replaceAll("_", " ")} / ${s.order} / street unknown`)));
  }

  function currentContext() {
    return contextLease && captureHealthy() && captureInScope(contextLease.value.capture) &&
      Date.now() < contextLease.expires && performance.now() < contextLease.deadline ? contextLease.value : null;
  }

  function clearContext() {
    if (contextFloor) contextFloor.closed = true;
    contextLease = null;
  }

  function admitContext(value, roundTripMs, boundary) {
    const context = value.tableContext;
    const capture = context?.capture;
    const sourceBinding = capture ? [capture.service_instance_id, capture.session_id, capture.capture_session_id,
      capture.source_id, capture.epoch, capture.width, capture.height].join("|") : null;
    if (boundary || !captureHealthy() || !captureInScope(capture, value) || value.sequence <= recoveryAfterSequence) {
      clearContext();
      if (boundary) { tableBinding = contextSourceBinding = confirmedTableId = null; tableBoundaryCapture = null; occupantFences.clear(); retainedIdentities.clear(); }
      return;
    }
    if (!context) { clearContext(); return; }
    const same = contextFloor?.sourceBinding === sourceBinding && contextFloor.sequence === capture.sequence;
    if (contextFloor?.sourceBinding === sourceBinding && (capture.sequence < contextFloor.sequence ||
        capture.captured_at_unix_ms < contextFloor.captured || same && (contextFloor.closed ||
          contextFloor.original !== JSON.stringify(capture) || context.expires > contextFloor.expires))) { clearContext(); return; }
    const remaining = context.expires - Date.now() - roundTripMs;
    if (capture.captured_at_unix_ms > Date.now() || remaining <= 0) { clearContext(); return; }
    if (contextSourceBinding !== null && contextSourceBinding !== sourceBinding ||
        confirmedTableId !== null && context.tableId !== null && confirmedTableId !== context.tableId) {
      clearRetained(); occupantFences.clear(); tableBoundaryCapture = capture.captured_at_unix_ms;
    }
    if (contextSourceBinding !== sourceBinding) confirmedTableId = null;
    if (context.tableId !== null) confirmedTableId = context.tableId;
    contextSourceBinding = sourceBinding;
    tableBinding = [sourceBinding, confirmedTableId].join("|");
    contextLease = { value: context, expires: Math.min(context.expires, same ? contextLease?.expires ?? 0 : Infinity),
      deadline: Math.min(performance.now() + remaining, same ? contextLease?.deadline ?? 0 : Infinity,
        recordingLease?.deadline ?? Infinity) };
    contextFloor = { sourceBinding, sequence: capture.sequence, captured: capture.captured_at_unix_ms,
      original: JSON.stringify(capture), expires: contextLease.expires, closed: false };
    for (const entry of context.seats) {
      const lastIdentity = retainedIdentities.get(entry.seat);
      if (entry.occupancy === "empty" || lastIdentity && lastIdentity.epoch !== entry.occupantEpoch) retainedIdentities.delete(entry.seat);
      if (entry.identity && entry.continuity === "confirmed") {
        retainedIdentities.set(entry.seat, { identity: entry.identity, epoch: entry.occupantEpoch,
          binding: tableBinding, capture: context.capture });
      }
      const previous = occupantFences.get(entry.seat);
      if (entry.occupancy === "empty" || entry.continuity === "confirmed" && entry.occupancy === "occupied" &&
          (!previous || previous.epoch !== entry.occupantEpoch || previous.empty)) {
        retainedNumbers.delete(`seats.${entry.seat}.displayed_stack`);
        occupantFences.set(entry.seat, { epoch: entry.occupantEpoch, captured: capture.captured_at_unix_ms,
          empty: entry.occupancy === "empty" });
      }
    }
  }

  function fencedObservation(observation) {
    if (!observation) return null;
    if (tableBoundaryCapture !== null && observation.captured < tableBoundaryCapture) return null;
    const original = observation.captureRef;
    if (observation.captureRefPresent && (!captureInScope(original) || original.captured_at_unix_ms !== observation.captured ||
        observation.expires > original.captured_at_unix_ms + MAX_LEASE_MS)) return null;
    const valid = field => {
      if (!Object.hasOwn(observation.fieldCaptures, field)) return true;
      const capture = observation.fieldCaptures[field];
      return captureInScope(capture) && capture.captured_at_unix_ms <= observation.captured &&
        observation.expires <= capture.captured_at_unix_ms + MAX_LEASE_MS && Date.now() < capture.captured_at_unix_ms + MAX_LEASE_MS;
    };
    return { ...observation, amounts: { ...observation.amounts,
      pot_size: valid("pot_size") ? observation.amounts.pot_size : null },
    board: observation.board.map((card, index) => valid(`board_slots.${index + 1}`) ? card : null),
    seats: observation.seats.map(entry => {
      const fence = occupantFences.get(entry.seat);
      const fields = { ...entry, displayed_stack: valid(`seats.${entry.seat}.displayed_stack`) ? entry.displayed_stack : null,
        visible_wager: valid(`seats.${entry.seat}.visible_wager`) ? entry.visible_wager : null };
      if (!fence || !fence.empty && (entry.occupantEpoch === fence.epoch ||
          entry.occupantEpoch == null && observation.captured >= fence.captured)) return fields;
      return { ...entry, displayed_stack: null, visible_wager: null, occupied: null, status: null, badge: null,
        dealer: null, small_blind: null, big_blind: null, acting: null };
    }) };
  }

  function initializeTable() {
    if (tableNodes) return;
    const seats = SEAT_LOCATIONS.map((location, index) => {
      const seat = index + 1;
      const item = make("li", "seat-reading");
      data(item, "seat", seat);
      const heading = make("div", "seat-heading");
      const button = make("button", "seat-select");
      button.type = "button";
      attribute(button, "aria-controls", "player-details");
      attribute(button, "aria-expanded", "false");
      const identity = make("span", "seat-identity", "Unknown player");
      button.append(make("span", "seat-number", `Seat ${seat}`), identity, make("span", "seat-location", location));
      button.addEventListener("click", () => {
        selectedSeat = seat;
        selectedOccupant = null;
        selectedAssociationChanged = false;
        renderTableSeats(fencedObservation(activeLease?.observation || null));
        node("player-title").focus();
      });
      const markers = make("span", "seat-markers");
      heading.append(button, markers);
      const amounts = make("dl", "seat-amounts");
      const fields = {};
      for (const [label, key] of [["Stack", "displayed_stack"], ["Wager", "visible_wager"]]) {
        const field = make("div");
        const value = make("dd", "unknown-value", "-");
        const reason = make("dd", "field-reason last-read-label");
        field.append(make("dt", "", label), value, reason);
        fields[key] = { value, reason };
        amounts.append(field);
      }
      const freshness = make("p", "seat-freshness", "Unknown");
      const revealed = make("ul", "cards seat-revealed-cards");
      revealed.hidden = true;
      const revealedSlots = Array.from({ length: 2 }, () => {
        const item = make("li", "playing-card unknown-card");
        const rank = make("span", "", "-"), suit = make("span");
        item.append(rank, suit); revealed.append(item); return { item, rank, suit };
      });
      item.append(heading, amounts, freshness, revealed);
      node("seat-readings").append(item);
      return { item, button, identity, markers, fields, freshness, revealed, revealedSlots };
    });
    const board = Array.from({ length: 5 }, () => {
      const item = make("div", "playing-card unknown-card");
      attribute(item, "role", "img");
      const rank = make("span", "card-rank", "-");
      const suit = make("span", "card-suit", "");
      item.append(rank, suit); node("board-cards").append(item);
      return { item, rank, suit };
    });
    const profile = Object.fromEntries(PROFILE_METRICS.map(([key, label]) => {
      const row = make("div");
      const title = make("dt", "", label);
      const value = make("dd", "unknown-value", "-");
      const state = make("dd", "metric-state", "Unknown");
      row.append(title, value, state); node("player-stats").append(row);
      return [key, { title, value, state }];
    }));
    const details = Object.fromEntries(["Identity", "Occupancy", "Stack", "Wager", "Badge"].map(label => {
      const row = make("div"), value = make("dd");
      row.append(make("dt", "", label), value); node("player-fields").append(row); return [label, value];
    }));
    const visual = SEAT_LOCATIONS.map((_, index) => {
      const row = make("li", "seat-reading"), badge = make("p"), wager = make("p");
      row.append(make("h4", "", `Seat ${index + 1}`), badge, wager); node("visual-seats").append(row);
      return { badge, wager };
    });
    tableNodes = { seats, board, profile, details, visual };
  }

  function renderBoard(observation) {
    const visual = visualLease?.value;
    const history = historicalVisual && retentionAllowed() && captureInScope(historicalVisual.captureRef) ? historicalVisual.lastBoard : null;
    const nativeEmpty = observation?.boardCount === 0 || !!observation && !observation.partial && observation.board.length === 0;
    const visualEmpty = visual?.boardSlots?.every(row => row.status === "empty") || visual?.cards?.length === 0;
    const rendered = [];
    for (const [index, slot] of tableNodes.board.entries()) {
      const native = observation?.board[index];
      const live = !nativeEmpty && (visual?.boardSlots?.[index]?.card || visual?.cards?.[index]);
      const previous = !nativeEmpty && !visualEmpty && visual?.boardSlots?.[index]?.status !== "empty" ? history?.[index] : null;
      const card = native || live || previous?.card;
      const state = native ? "current" : live ? "provisional" : previous?.card ? "last-read" : nativeEmpty ? "current" : visualEmpty ? "provisional" : "unknown";
      const source = native || nativeEmpty ? originalFor(observation, `board_slots.${index + 1}`) :
        live ? visual.boardSlots?.[index]?.capture || visual.captureRef : previous?.card ? previous.capture : visualEmpty ? visual.captureRef : null;
      const street = index < 3 ? "Flop" : index === 3 ? "Turn" : "River";
      rendered.push({ card, state });
      patchText(slot.rank, card?.rank || "-");
      patchText(slot.suit, card ? String.fromCodePoint(SUITS[card.suit].symbol) : "");
      slot.item.classList.toggle("unknown-card", !card);
      slot.item.classList.toggle("red-suit", !!card && SUITS[card.suit].red);
      attribute(slot.item, "aria-label", card ? `${state === "last-read" ? "Last seen, not current" : state === "provisional" ? "Provisional" : "Experimental"} ${street}${index < 3 ? ` card ${index + 1}` : ""}: ${RANK_NAMES[card.rank] || card.rank} of ${SUITS[card.suit].name}` :
        `${street}${index < 3 ? ` card ${index + 1}` : ""}: ${nativeEmpty || visualEmpty ? "no community card observed" : "unknown, no verified card"}`);
      attribute(slot.item, "data-street", street);
      attribute(slot.item, "title", street + (state === "last-read" ? ": last seen, not current" : state === "provisional" ? ": provisional recognition" : ""));
      publishField(slot.item, `board_slots.${index + 1}`, card ? card.rank + card.suit : null, state, source);
    }
    const count = rendered.filter(row => row.card).length;
    const lastSeen = rendered.some(row => row.card && row.state === "last-read");
    data(node("board-cards"), "reading", lastSeen ? "last-read" : visual && !observation?.board.some(Boolean) ? "provisional" : count || nativeEmpty ? "current" : "unknown");
    const prefix = rendered.slice(0, 3).every(row => row.card) ? rendered[4].card ? 5 : rendered[3].card ? 4 : 3 : 0;
    const stage = { 3: "Flop", 4: "Turn", 5: "River" }[prefix];
    if (stage && (!observation || observation.phase === "unknown")) text("game-phase", stage + (lastSeen ? " / last seen" : ""));
    text("board-reason", nativeEmpty ? "No community cards" : visualEmpty ? "No community cards observed / hand boundary unknown" : lastSeen ? "Last seen board cards are dimmed; not current" : count ? "Source-bound experimental cards; unreadable slots stay unknown" : `Unknown / ${reasonFor(observation, "board_slots.1")}`);
  }

  function renderTableSeats(observation) {
    const context = currentContext();
    const visual = visualLease?.value;
    for (const [index, slot] of tableNodes.seats.entries()) {
      const seat = index + 1;
      const entry = observation?.seats[index] || { seat };
      const owner = context?.seats[index];
      const fence = occupantFences.get(seat);
      const fallback = !fence || !fence.empty && visual?.captured >= fence.captured ?
        visual?.seats.find(value => value.seat === seat) : null;
      const vacancy = fence?.empty === true;
      const exposed = fallback ? visual.revealedSeats?.find(row => row.seat === seat) : null;
      const validPair = !vacancy && exposed?.faceCount > 0 &&
        (!exposed.identity || owner?.identity === exposed.identity && owner.occupantEpoch === exposed.epoch);
      slot.revealed.hidden = !validPair;
      attribute(slot.revealed, "aria-label", `Visible cards at physical seat ${seat}; ${exposed?.identity ? "source-bound player association" : "player association unconfirmed"}; not proof of hero or showdown phase`);
      for (const [cardIndex, cardNode] of slot.revealedSlots.entries()) {
        const reading = validPair ? exposed.readings[cardIndex] : null;
        const card = reading?.card;
        patchText(cardNode.rank, card?.[0] || "?");
        patchText(cardNode.suit, card ? String.fromCodePoint(SUITS[card[1]].symbol) : "");
        cardNode.item.classList.toggle("unknown-card", !card);
        cardNode.item.classList.toggle("red-suit", !!card && SUITS[card[1]].red);
        attribute(cardNode.item, "aria-label", card ? `Seat ${seat} visible card ${cardIndex + 1}: ${RANK_NAMES[card[0]] || card[0]} of ${SUITS[card[1]].name}, provisional` : `Seat ${seat} visible card ${cardIndex + 1}: unreadable`);
        publishField(cardNode.item, `seats.${seat}.revealed_cards.${cardIndex + 1}`, card || null, card ? "provisional" : "unknown", reading?.capture || null);
      }
      const remembered = !vacancy && retentionAllowed() && retainedIdentities.get(seat);
      const lastIdentity = !owner?.identity && remembered?.binding === tableBinding &&
        (!owner || remembered.epoch === owner.occupantEpoch) ? remembered : null;
      const name = owner?.identity || lastIdentity?.identity || (owner?.occupancy === "empty" ? "Empty seat" :
        owner?.occupancy === "occupied" || entry.occupied === true ? "Name pending" : "Seat status pending");
      patchText(slot.identity, name);
      slot.identity.classList.toggle("retained-identity", !!lastIdentity);
      attribute(slot.identity, "title", lastIdentity ? `Last seen ${new Date(lastIdentity.capture.captured_at_unix_ms).toISOString()}; current identity uncertain` : owner?.identity ? "Recognized player; experimental source-bound identity" : "Player identity unavailable");
      attribute(slot.button, "aria-label", `Seat ${seat}, ${SEAT_LOCATIONS[index]}, ${name}${lastIdentity ? ", last seen; current association uncertain" : ""}. Open Monitor details`);
      attribute(slot.button, "aria-expanded", selectedSeat === seat);
      data(slot.item, "selected", selectedSeat === seat);
      data(slot.item, "hero", context?.heroSeat === seat || !context && observation?.heroSeat === seat);
      publishField(slot.identity, `seats.${seat}.identity`, owner?.identity || lastIdentity?.identity || null,
        owner?.identity ? context.provisional ? "provisional" : owner.status : lastIdentity ? "last-read" : "unknown",
        owner?.identity ? context.capture : lastIdentity?.capture || null);
      const occupancy = owner?.occupancy ?? "unknown";
      publishField(slot.item, `seats.${seat}.occupancy`, occupancy, occupancy === "unknown" ? "unknown" : context?.provisional ? "provisional" : owner?.status || "current", owner ? context.capture : originalFor(observation, `seats.${seat}.occupied`));
      const markers = [occupancy === "empty" ? "Empty" : null,
        vacancy ? null : entry.status?.replaceAll("_", " "), vacancy ? null : entry.dealer === true ? "BTN" : null,
        vacancy ? null : entry.small_blind === true ? "SB" : null, vacancy ? null : entry.big_blind === true ? "BB" : null,
        vacancy ? null : entry.acting === true ? "Acting" : null, context?.heroSeat === seat ? "Self" : null];
      let hasCurrent = false, hasRetained = false, hasProvisional = !!context?.provisional || owner?.status === "provisional";
      for (const key of ["displayed_stack", "visible_wager"]) {
        const path = `seats.${seat}.${key}`;
        const target = slot.fields[key];
        const quick = numericLease?.value.seats[index][key === "displayed_stack" ? "stack" : "wager"];
        const nativeCapture = originalFor(observation, path);
        const nativeValue = integer(entry[key]) && !numericSupersedes(path, nativeCapture) ? entry[key] : null;
        const visualWager = fallback?.wager != null && !numericSupersedes(path, visual?.captureRef) ? fallback.wager : null;
        const fast = newestNumeric(quick, nativeValue, nativeCapture, fence);
        const competingCapture = integer(nativeValue) ? nativeCapture :
          key === "visible_wager" && fallback?.wager != null ? visual.captureRef : retainedNumbers.get(path)?.capture || null;
        const cleared = numericCleared(quick, competingCapture, fence);
        const last = !vacancy && !fast && !cleared && key === "displayed_stack" && !integer(nativeValue) ? retainedNumbers.get(path) : null;
        const provisional = !vacancy && !cleared && key === "visible_wager" && !integer(nativeValue) ? visualWager : null;
        const current = !vacancy && !fast && !cleared && integer(nativeValue);
        const value = fast ? fast.literal : current ? literalAmount(nativeValue, entry[`${key}_text`]) : last ? last.literal : provisional ?? "-";
        const state = fast || cleared ? "provisional" : current ? "current" : last ? "last-read" : provisional !== null && provisional !== undefined ? "provisional" : "unknown";
        patchText(target.value, value);
        target.value.classList.toggle("retained-number", !!last);
        target.value.classList.toggle("unknown-value", state === "unknown");
        patchText(target.reason, last ? retainedLabel(path) : state === "unknown" ? reasonFor(observation, path, key === "visible_wager" ? "missing-capability" : "insufficient-context") : "");
        publishField(target.value, path, value, state, fast?.capture || (cleared ? quick.capture : current ? originalFor(observation, path) : last?.capture || (state === "provisional" ? visual.captureRef : null)));
        hasCurrent ||= current; hasRetained ||= !!last; hasProvisional ||= state === "provisional";
      }
      const nativeBadge = !vacancy && entry.badge != null;
      const badge = nativeBadge ? entry.badge : !vacancy ? fallback?.badge || (fallback?.absent ? "none" : null) : null;
      const badgeState = badge ? nativeBadge ? "current" : "provisional" : "unknown";
      if (badge && badge !== "none") markers.push(badge.replaceAll("_", " ").toUpperCase());
      patchText(slot.markers, markers.filter(Boolean).join(" / "));
      publishField(slot.markers, `seats.${seat}.badge`, badge || null, badgeState, badgeState === "current" ? originalFor(observation, `seats.${seat}.badge`) : badge ? visual.captureRef : null);
      hasProvisional ||= badgeState === "provisional";
      const state = hasProvisional ? "provisional" : hasCurrent || occupancy !== "unknown" ? "current" : hasRetained ? "last-read" : "unknown";
      const age = sourceAge(context?.capture || (hasCurrent ? originalFor(observation, `seats.${seat}.displayed_stack`) : null));
      const label = state === "provisional" ? "Provisional" : state === "last-read" ? "Last seen / not current" : state === "current" ? "Current" : "Unknown";
      patchText(slot.freshness, `${label}${lastIdentity ? " / last-seen name; association uncertain" : ""}${hasRetained && state !== "last-read" ? " / last-seen stack" : ""}${age !== null ? ` / ${ageSummary(age)}` : ""}`);
      data(slot.freshness, "reading", state);
    }
    const known = context?.seats.every(entry => entry.occupancy !== "unknown");
    text("occupancy-summary", known ? `${context.seats.filter(entry => entry.occupancy === "occupied").length}/6 seats occupied` : "Occupancy uncertain");
    renderPlayerDetails(context);
  }

  function closePlayerDetails() {
    const previous = selectedSeat;
    selectedSeat = selectedOccupant = null;
    selectedAssociationChanged = false;
    renderTableSeats(fencedObservation(activeLease?.observation || null));
    if (previous !== null) tableNodes.seats[previous - 1].button.focus();
  }

  function renderPlayerDetails(context) {
    node("player-details").hidden = selectedSeat === null;
    if (selectedSeat === null) return;
    const entry = context?.seats[selectedSeat - 1];
    const slot = tableNodes.seats[selectedSeat - 1];
    const occupant = entry?.identity ? `${tableBinding}|${entry.occupantEpoch}|${entry.identity}` : null;
    const replaced = selectedOccupant !== null && selectedOccupant !== occupant;
    selectedAssociationChanged ||= replaced;
    selectedOccupant = occupant;
    text("player-title", `Seat ${selectedSeat} / ${slot.identity.textContent}`);
    text("player-association", `${selectedAssociationChanged ? "Occupant changed or association lost. " : ""}${entry ? `${entry.occupancy} / ${entry.status} / continuity ${entry.continuity}` : "Unknown / no current roster lease"}`);
    const reference = context?.capture;
    const identityTime = reference ? ` / original ${new Date(reference.captured_at_unix_ms).toISOString()} / ${ageSummary(sourceAge(reference))} source age` : "";
    patchText(tableNodes.details.Identity, `${entry?.identity || "-"} / ${entry?.reason || "Unknown"}${identityTime}`);
    patchText(tableNodes.details.Occupancy, `${entry?.occupancy || "unknown"}${identityTime}`);
    for (const [label, field] of [["Stack", slot.fields.displayed_stack.value], ["Wager", slot.fields.visible_wager.value], ["Badge", slot.markers]]) {
      const source = JSON.parse(field.dataset.captureRef || "null");
      const captured = source?.captured_at_unix_ms;
      const literal = renderedFields.get(`seats.${selectedSeat}.badge`)?.receipt.value;
      patchText(tableNodes.details[label], `${label === "Badge" ? literal === "none" ? "No badge observed" : literal || "-" : field.textContent} / ${field.dataset.reading}` +
        (captured ? ` / original ${new Date(captured).toISOString()} / ${ageSummary(sourceAge(source))} source age` : " / original unavailable") +
        (source?.complete === false ? " / incomplete legacy capture IDs" : ""));
    }
    const profile = entry?.stats;
    const profileScopeCapture = profile?.capture.parent_capture || profile?.capture;
    const stats = profile && (tableBoundaryCapture === null || profileScopeCapture.captured_at_unix_ms >= tableBoundaryCapture) ? profile : null;
    text("player-stats-status", stats ? `Last observed client-displayed / ${stats.status}${stats.provisional || context?.provisional ? " / provisional recognition" : ""} / ${ageSummary(sourceAge(stats.capture))} source age / not current table amounts` : "Unknown / no owner-bound profile observed for this current player");
    for (const [key, label] of PROFILE_METRICS) {
      const metric = stats?.metrics[key], target = tableNodes.profile[key];
      patchText(target.title, metric?.label || label);
      patchText(target.value, metric?.literal || "-");
      patchText(target.state, metric ? metric.status : "unknown");
      target.value.classList.toggle("retained-number", !!stats);
      publishField(target.value, `selected_player.${key}`, metric?.literal || "-", stats ?
        `${metric.literal === "-" ? "unknown" : "last-observed"}/${metric.status}` : "unknown", stats?.capture || null);
    }
    text("player-stats-scope", `Sample size ${stats?.sample == null ? "unknown" : count(stats.sample)} / scope ${stats?.scope || "unknown"}`);
    text("player-stats-source", stats ? `Original ${new Date(stats.capture.captured_at_unix_ms).toISOString()} / service ${stats.capture.service_instance_id} / feed ${stats.capture.session_id} / source ${stats.capture.source_id} / epoch ${stats.capture.epoch} / sequence ${stats.capture.sequence} / producer capture ${stats.capture.captured_at_ms} ms / PNG SHA256 ${stats.capture.sha256}${stats.capture.parent_capture ? ` / separate popup, non-atomic / parent table sequence ${stats.capture.parent_capture.sequence} / parent PNG SHA256 ${stats.capture.parent_capture.sha256}` : ""}` : "Original profile capture unavailable");
    node("player-evidence").hidden = !stats?.evidenceId;
    attribute(node("player-evidence"), "href", stats?.evidenceId ? `/api/evidence/${stats.evidenceId}` : "#player-details");
  }

  function renderControls(id, labels) {
    const signature = JSON.stringify(ACTIONS.map(action => labels?.get(action) || null));
    if (node(id).dataset.controlsSignature === signature) return;
    data(node(id), "controlsSignature", signature);
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

  function amount(id, value, literal) {
    text(id, literalAmount(value, literal));
    node(id).classList.toggle("unknown-value", !integer(value));
  }

  function retentionAllowed() {
    const recorder = snapshot?.recording;
    return connected && !document.hidden && !(stopMatches() && ["requested", "unavailable"].includes(stopRequest.state)) && snapshot?.service && snapshot.source === "live" &&
      !snapshot.sourceBoundary && (["active", "verifying"].includes(snapshot.capture.state) ||
        snapshot.capture.state === "unavailable" && snapshot.capture.transient) &&
      snapshot.capture.epoch !== null && snapshot.capture.width !== null && snapshot.capture.height !== null &&
      snapshot.capture.heartbeat !== null && Date.now() < heartbeatExpires && performance.now() < heartbeatDeadline &&
      recorder?.status === "capturing" && recorder.mode === "inference-enabled" && recorder.inferenceEnabled &&
      snapshot.inferenceEnabled === true && snapshot.modelState === "ready" &&
      (!automaticPolicy(recorder.sourcePolicy) || ["verifying", "active"].includes(recorder.activityState) &&
        (!snapshot.automaticStartup || ["verifying", "active"].includes(snapshot.automaticStartup.status))) &&
      (recorder.sourcePolicy !== "automatic-sustained" || recordingLease?.feed === snapshot.session && recordingLease.service === snapshot.service) &&
      recordingFresh() && recordingBudgetOpen();
  }

  function experimentalAllowed() {
    return snapshot?.experimentalEnabled && snapshot.recording?.experimentalEnabled && snapshot.service &&
      snapshot.recording.sourcePolicy === "automatic-bounded" && snapshot.recording.status === "capturing" &&
      snapshot.recording.mode === "inference-enabled" && snapshot.recording.inferenceEnabled &&
      snapshot.capture.epoch !== null && snapshot.capture.width !== null && snapshot.capture.height !== null && captureHealthy();
  }

  function clearExperimental() {
    if (experimentalLease) {
      experimentalClosedKey = leaseKey(experimentalLease.value);
      experimentalFloor = { epoch: experimentalLease.value.epoch, generation: experimentalLease.value.generation };
    }
    experimentalLease = null;
    node("experimental-panel").hidden = true;
    text("experimental-age", "");
    node("experimental-candidates").replaceChildren();
  }

  function renderExperimental() {
    if (!experimentalLease) return;
    const value = experimentalLease.value;
    node("experimental-panel").hidden = false;
    const age = Math.max(0, Date.now() - value.captured,
      experimentalLease.sourceAge + performance.now() - experimentalLease.admitted);
    text("experimental-age", `${Math.floor(age)} ms original source age / diagnostic-only / not an admitted reading`);
    const row = make("div", "experimental-candidate");
    row.append(make("h3", "", `Physical seat ${value.seat} / ${SEAT_LOCATIONS[value.seat - 1]} / ${value.kind === "wager" ? "numeric-transfer candidate" : "scene/marker guesses"}`));
    if (value.kind === "wager") {
      row.append(make("p", "candidate-value", value.text === null ? "Unknown / no numeric candidate" : `Unvalidated numeric text: ${value.text}`));
      row.append(make("p", "small muted", `Inherited p5 donor cutoff: ${value.cutoff.toFixed(3)} / NOT a fitted p6 floor. ${value.scores.length ? `Glyph scores: ${value.scores.map(score => score.toFixed(3)).join(", ")}` : "Empty, overflow, invalid or below-cutoff glyphs stay unknown; empty is never zero."}`));
    } else {
      const labels = { occupied: "Occupancy guess", status: "Status guess", badge: "Badge guess", dealer: "Dealer-marker guess",
        small_blind: "Small-blind-marker guess", big_blind: "Big-blind-marker guess", acting: "Acting-marker guess" };
      const guesses = make("dl", "experimental-guesses");
      for (const guess of value.scene) {
        const item = make("div");
        item.append(make("dt", "", labels[guess.field]), make("dd", "", `${guess.guess ?? "Unknown"} / score ${guess.score === null ? "unknown" : guess.score.toFixed(3)} / unvalidated / no fitted floor`));
        guesses.append(item);
      }
      row.append(guesses);
    }
    node("experimental-candidates").replaceChildren(row);
  }

  function admitExperimental(value, previousSequence, roundTripMs, boundary) {
    const binding = [value.service, value.session, value.recording?.session, value.capture.epoch, value.capture.width, value.capture.height].join("|");
    if (experimentalBinding !== null && experimentalBinding !== binding) boundary = true;
    experimentalBinding = binding;
    const candidate = value.experimental;
    if (boundary || !experimentalAllowed() || !candidate || candidate.epoch !== value.capture.epoch) {
      clearExperimental();
      return;
    }
    const key = leaseKey(candidate);
    if (experimentalFloor && compareObservation(candidate, experimentalFloor) < 0) return;
    if (key === experimentalClosedKey || experimentalFloor && compareObservation(candidate, experimentalFloor) === 0 && !experimentalLease ||
        !experimentalLease && value.sequence <= previousSequence) { clearExperimental(); return; }
    if (experimentalLease && candidate.epoch === experimentalLease.value.epoch && candidate.generation === experimentalLease.value.generation &&
        candidate.captured !== experimentalLease.value.captured) { clearExperimental(); return; }
    const remaining = Math.min(MAX_LEASE_MS, candidate.remaining - roundTripMs, candidate.expires - Date.now());
    if (remaining <= 0 || candidate.captured > Date.now() || candidate.expires <= candidate.captured || candidate.expires > candidate.captured + MAX_LEASE_MS) { clearExperimental(); return; }
    const same = experimentalLease && leaseKey(experimentalLease.value) === key;
    experimentalLease = { value: candidate,
      deadline: Math.min(same ? experimentalLease.deadline : Infinity, performance.now() + remaining, recordingLease.deadline),
      expires: Math.min(same ? experimentalLease.expires : Infinity, candidate.expires, recordingLease.expires),
      sourceAge: same ? experimentalLease.sourceAge : Math.max(0, Date.now() - candidate.captured),
      admitted: same ? experimentalLease.admitted : performance.now() };
    experimentalFloor = { epoch: candidate.epoch, generation: candidate.generation };
    renderExperimental();
  }

  function clearRetained() {
    retainedNumbers.clear();
    retainedIdentities.clear();
    historicalVisual = null;
    numericLease = numericFloor = null;
    numericSupersession.clear();
    retainedScope = null;
  }

  function updateRetainedScope() {
    if (!retentionAllowed()) { clearRetained(); return false; }
    const scope = { service: snapshot.service, session: snapshot.session, recording: snapshot.recording.session,
      sourceId: snapshot.capture.sourceId, epoch: snapshot.capture.epoch,
      width: snapshot.capture.width, height: snapshot.capture.height };
    const changed = retainedScope && Object.keys(scope).some((key) => retainedScope[key] !== scope[key]);
    if (changed) { retainedNumbers.clear(); retainedIdentities.clear(); historicalVisual = null; numericLease = numericFloor = null; numericSupersession.clear(); }
    retainedScope = scope;
    if (snapshot.fieldsChanged) for (const value of retainedNumbers.values()) value.changed = true;
    return !!changed;
  }

  function rememberNumbers(observation) {
    if (!retainedScope || !retentionAllowed()) return;
    // Admission remains the live lease's job. This map never becomes an Observation.
    const fields = [["pot_size", observation.amounts.pot_size, observation.amountTexts.pot_size],
      ...observation.seats.map((entry) => [`seats.${entry.seat}.displayed_stack`, entry.displayed_stack, entry.displayed_stack_text])];
    for (const [field, value, literal] of fields) {
      if (!integer(value) || observation.fieldStatuses[field]?.status !== "accepted") continue;
      const previous = retainedNumbers.get(field);
      const capture = originalFor(observation, field);
      const captured = capture.captured_at_unix_ms;
      if (numericSupersedes(field, capture) || previous && previous.captured > captured) continue;
      if (previous && (captured < previous.captured || previous.key === leaseKey(observation))) continue;
      const age = Math.max(0, Date.now() - captured,
        previous?.captured === captured ? Math.max(previous.age,
          previous.sourceAge + performance.now() - previous.mono) : 0);
      retainedNumbers.set(field, { value, literal: literalAmount(value, literal), captured,
        capture, key: leaseKey(observation), mono: performance.now(), sourceAge: age, age, changed: false });
    }
  }

  function retainedLabel(field, precise = false) {
    const value = retainedNumbers.get(field);
    value.age = Math.max(value.age, Date.now() - value.captured,
      value.sourceAge + performance.now() - value.mono);
    return `Last read / ${value.changed ? "Source changed" : "Awaiting recheck"} / ${precise ? `${count(Math.floor(value.age))} ms` : ageSummary(value.age)} source age / not current`;
  }

  function retainedCount(observation) {
    return [...retainedNumbers.keys()].filter((field) => !integer(field === "pot_size" ? observation?.amounts.pot_size :
      observation?.seats[Number(field.split(".")[1]) - 1]?.displayed_stack)).length;
  }

  function renderAction(observation) {
    const role = observation ? observation.role : "uncertain";
    const advice = observation && adviceLease ? adviceLease.value : null;
    node("suggested-action").hidden = !observation;
    node("suggested-action").dataset.role = role;
    text("action-title", advice ? "Experimental recommendation" : "Observation status");
    text("analysis-status", advice ? "Experimental analysis" : "Analysis unavailable");
    status("role-status", ROLE_NAMES[role], role === "your_turn" ? "warning" : "neutral");
    node("role-status").hidden = role === "uncertain";
    text("action-move", advice ? ACTION_NAMES[advice.action] : ROLE_MESSAGES[role]);
    text("action-amount", advice && !["fold", "check"].includes(advice.action) ? chips(advice.amount) : "-");
    node("action-amount-wrap").hidden = !advice || ["fold", "check"].includes(advice.action);
    text("action-reason", advice ? `Native Pipeline / experimental / quality_approved: false. Estimated EV: ${advice.ev.toFixed(2)} (native units). Equity: ${percent(advice.equity)}.${advice.odds === null ? "" : ` Required equity: ${percent(advice.odds)}.`}${advice.breakEven === null ? "" : ` Break-even: ${percent(advice.breakEven)}.`} No poker action is sent.` :
      role === "observing" ? "Readings and history continue while you observe." :
      role === "seated_waiting" ? "Readings and history continue between turns." : "No current source-qualified analysis. Partial chips and stacks do not establish an action.");
    node("action-reason").hidden = role === "uncertain";
  }

  function renderObservation(observation) {
    initializeTable();
    observation = fencedObservation(observation);
    if (!retentionAllowed()) clearRetained();
    renderAction(observation);
    const readable = !!observation && (!observation.partial || observation.phase !== "unknown" ||
      observation.boardCount !== null || observation.board.some(Boolean) || observation.amounts.pot_size !== null ||
      observation.seats.some((entry) => entry.displayed_stack !== null || entry.visible_wager !== null ||
        [entry.occupied, entry.status, entry.badge, entry.dealer, entry.small_blind, entry.big_blind, entry.acting].some((v) => v != null)));
    const retained = retainedCount(observation) > 0;
    const heading = node("observation-title");
    const context = currentContext();
    if (heading) patchText(heading, !readable && retained ? "Last-read amounts" : readable ? "Current readings" : "Table / independent observations");
    node("monitor-readings").hidden = false;
    data(node("monitor-readings"), "reading", readable || context || visualLease || numericLease ? "current" : retained ? "last-read" : "unknown");
    data(node("monitor-readings"), "numericReading", numericLease ? "provisional" : readable ? "current" : "unknown");
    node("monitor-empty").hidden = readable || retained || !!context || !!visualLease || !!numericLease;
    node("monitor-grid").classList.toggle("no-reading", !readable && !retained && !context && !visualLease && !numericLease);
    node("history-panel").hidden = node("monitor-grid").classList.contains("no-history");
    if (!readable) text("monitor-empty", observation ? "Reading uncertain" : connected && snapshot && snapshot.capture.state === "blocked" ?
      "Waiting for a unique CoinPoker game window." : connected && snapshot && snapshot.source === "live" ?
        "Reading uncertain" : "Waiting for a table reading.");
    renderCards("hero-cards", observation ? observation.hero : [], 2, "Hero");
    text("game-phase", observation && observation.phase !== "unknown" ? PHASE_NAMES[observation.phase] : "-");
    renderBoard(observation);
    node("hero-card-group").hidden = !observation?.hero.length && !observation?.heroSeat || observation?.role === "observing";
    text("hero-label", observation?.heroSeat ? `Hero / seat ${observation.heroSeat}` : "Hero");
    text("hero-reason", observation?.hero.length ? "" : reasonFor(observation, "hero_cards", "missing-capability"));
    renderControls("control-states", observation ? observation.controls : null);
    text("acting-seat", observation && observation.actingSeat !== null ? `Seat ${observation.actingSeat}` : "-");
    const observing = observation && observation.role === "observing";
    const seated = observation && ["seated_waiting", "your_turn"].includes(observation.role);
    text("call-label", observing ? observation.actingSeat === null ? "Acting-seat call" : `Acting seat ${observation.actingSeat} to call` : seated ? "Your call" : "Call");
    amount("amount-call", observation ? observing ? observation.amounts.acting_to_call : seated ? observation.amounts.to_call : null : null);
    for (const [id, key] of [["amount-stack", "hero_chips"], ["amount-min", "min_raise_to"], ["amount-max", "max_raise_to"]]) amount(id, observation ? observation.amounts[key] : null, observation?.amountTexts[key]);
    const nativePotCapture = originalFor(observation, "pot_size");
    const nativePot = integer(observation?.amounts.pot_size) && !numericSupersedes("pot_size", nativePotCapture) ? observation.amounts.pot_size : null;
    const fastPot = newestNumeric(numericLease?.value.pot, nativePot, nativePotCapture);
    const clearedPot = numericCleared(numericLease?.value.pot, integer(nativePot) ? nativePotCapture : retainedNumbers.get("pot_size")?.capture || null);
    const retainedPot = !fastPot && !clearedPot && nativePot == null && retainedNumbers.has("pot_size");
    amount("amount-pot", fastPot?.value ?? (clearedPot ? null : retainedPot ? retainedNumbers.get("pot_size").value : nativePot),
      fastPot?.literal ?? (retainedPot ? retainedNumbers.get("pot_size").literal : observation?.amountTexts.pot_size));
    node("amount-pot").classList.toggle("retained-number", retainedPot);
    publishField(node("amount-pot"), "pot_size", node("amount-pot").textContent,
      fastPot || clearedPot ? "provisional" : retainedPot ? "last-read" : nativePot != null ? "current" : "unknown",
      fastPot?.capture ?? (clearedPot ? numericLease.value.pot.capture : retainedPot ? retainedNumbers.get("pot_size").capture : originalFor(observation, "pot_size")));
    text("pot-reason", fastPot || clearedPot ? "" : retainedPot ? retainedLabel("pot_size") : nativePot != null ? "" : reasonFor(observation, "pot_size"));
    text("stack-reason", observation?.amounts.hero_chips != null ? "" : reasonFor(observation, "hero_chips", "missing-capability"));
    node("hero-stack-reading").hidden = observing || observation?.amounts.hero_chips == null;
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
    renderTableSeats(observation);
    node("seats-reading").hidden = false;
    const metrics = observation ? observation.metrics : {};
    const oddsSeat = observing ? observation.actingSeat : metrics.odds ? metrics.odds.seat : null;
    text("metric-odds-label", observing ? oddsSeat === null ? "Acting-seat pot odds / required equity" : `Seat ${oddsSeat} pot odds / required equity` : "Pot odds / required equity");
    text("metric-rank", metrics.rank || "-");
    text("metric-odds", percent(metrics.odds ? metrics.odds.pct : null));
    text("metric-draw-outs", count(metrics.draw ? metrics.draw.outs : null));
    text("metric-draw-next", percent(metrics.draw ? metrics.draw.next : null));
    text("metric-draw-river", percent(metrics.draw ? metrics.draw.river : null));
    text("metric-equity", percent(metrics.equity));
    node("metrics-readings").hidden = !Object.values(metrics).some(value => value !== null && value !== undefined);
    text("reading-limit", `Physical seats, not hand positions. Stacks are remaining chips, not bets. Untrained fields stay unknown; observed amounts do not imply recommendations.${observation?.analysisQualified ? " Analysis is experimental / quality_approved: false; missing metrics stay unknown." : snapshot?.recording?.sourcePolicy === "automatic-sustained" ? " Native action inputs and complete betting history remain unavailable; provisional sightings above are separate." : ""}${retained ? " Last-read amounts are not current. Awaiting recheck means verification expired, not that a bet occurred. Source changed refers to the image, not a confirmed amount change." : ""}`);
    renderDiagnostics(observation);
    renderSource(observation);
  }

  function normalizeRecording(value) {
    if (!record(value) || !["capture-only", "inference-enabled"].includes(value.mode) ||
        !["idle", "capturing", "stopped", "failed", "interrupted"].includes(value.status) ||
        typeof value.inference_enabled !== "boolean") return null;
    const sourcePolicy = value.source_policy === undefined ? "manual" : allowed(value.source_policy, ["manual", "automatic-bounded", "automatic-sustained"], null);
    const activityState = value.activity_state === undefined ? sourcePolicy === "manual" && value.mode === "inference-enabled" ? "active" : "idle" :
      allowed(value.activity_state, Object.keys(ACTIVITY_LABELS), null);
    if (!sourcePolicy || !activityState) return null;
    const result = { session: opaqueId(value.session_id) ? value.session_id : null,
      mode: value.mode, status: value.status, sourcePolicy, activityState, inferenceEnabled: value.inference_enabled === true,
      experimentalEnabled: value.experimental_bet_action === true };
    for (const key of ["elapsed_ms", "max_duration_ms", "max_frames", "recorded_frames", "recorded_bytes", "remaining_ms", "distinct_opportunities", "target_opportunities", "opportunity_deficit", "capture_failures", "estimated_missed_samples", "gap_count", "max_gap_ms", "updated_at_unix_ms"]) result[key] = integer(value[key]) ? value[key] : null;
    result.stopReason = allowed(value.stop_reason, ["operator-stop", "duration-limit", "frame-limit", "disk-limit", "recorder-failure",
      "source-unavailable", "source-changed", "capture-failed", "child-exited", "child-failed", "native-stalled", "receipt-invalid",
      "log-limit", "supervisor-error", "status-stale", "child-stop-unconfirmed", "inference-failed", "publication-failed",
      "model-not-ready", "feed-failed", "table-activity-unconfirmed", "automatic-discovery-timeout"], null);
    if (sourcePolicy === "automatic-sustained") {
      const evidence = value.evidence;
      const evidenceKeys = ["status", "stop_reason", "elapsed_ms", "max_duration_ms", "max_frames", "max_bytes", "recorded_frames", "recorded_bytes"];
      if (value.receipt_version !== 2 || !result.session || value.mode !== "inference-enabled" ||
          value.experimental_bet_action !== false || !["idle", "verifying", "active"].includes(value.activity_state) ||
          !["max_duration_ms", "max_frames", "remaining_ms"].every(key => value[key] === null) ||
          !integer(value.elapsed_ms) || !integer(value.updated_at_unix_ms) || value.updated_at_unix_ms <= 0 ||
          value.stop_reason !== null && result.stopReason === null ||
          ["idle", "capturing"].includes(value.status) && value.stop_reason !== null ||
          !record(evidence) || evidenceKeys.some(key => !Object.hasOwn(evidence, key)) ||
          Object.keys(evidence).some(key => !evidenceKeys.includes(key)) ||
          !["active", "ended"].includes(evidence.status) ||
          !integer(evidence.max_duration_ms) || evidence.max_duration_ms < 1 || evidence.max_duration_ms > 600000 ||
          !integer(evidence.max_frames) || evidence.max_frames < 1 || evidence.max_frames > 1200 || evidence.max_bytes !== 1073741824 ||
          !integer(evidence.elapsed_ms) || evidence.elapsed_ms > evidence.max_duration_ms ||
          !integer(evidence.recorded_frames) || evidence.recorded_frames > evidence.max_frames ||
          !integer(evidence.recorded_bytes) || evidence.recorded_bytes > evidence.max_bytes ||
          value.recorded_frames !== evidence.recorded_frames || value.recorded_bytes !== evidence.recorded_bytes) return null;
      if (evidence.status === "active" ? evidence.stop_reason !== null || evidence.elapsed_ms >= evidence.max_duration_ms ||
          evidence.recorded_frames >= evidence.max_frames || evidence.recorded_bytes >= evidence.max_bytes :
        !["duration-limit", "frame-limit", "disk-limit"].includes(evidence.stop_reason) ||
          evidence.stop_reason === "duration-limit" && evidence.elapsed_ms !== evidence.max_duration_ms ||
          evidence.stop_reason === "frame-limit" && evidence.recorded_frames !== evidence.max_frames) return null;
      result.evidence = { ...evidence };
    } else if (value.receipt_version === 2 || value.evidence !== undefined) return null;
    return result;
  }

  const duration = (ms) => integer(ms) ? `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}` : "unknown";

  function recordingFresh() {
    const updated = snapshot?.recording?.updated_at_unix_ms;
    if (snapshot?.recording?.sourcePolicy === "automatic-sustained") {
      return connected && recordingLease?.session === snapshot.recording.session && updated === recordingLease.receiptHeartbeat &&
        updated <= Date.now() + 500 && Date.now() < recordingLease.receiptExpires && performance.now() < recordingLease.receiptDeadline;
    }
    return connected && integer(updated) && updated > 0 && updated <= Date.now() + 500 && Date.now() - updated < 5000;
  }

  function recordingBudgetOpen() {
    if (!recordingLease || snapshot?.recording?.session !== recordingLease.session) return false;
    if (Date.now() >= recordingLease.expires || performance.now() >= recordingLease.deadline) recordingLease.closed = true;
    return !recordingLease.closed;
  }

  function updateRecordingLease(recorder, roundTripMs) {
    const replaced = !!recordingLease && recorder?.session !== recordingLease.session;
    if (replaced) {
      retiredRecordings.add(recordingLease.session);
      recordingLease = null;
    }
    if (!recorder) return replaced;
    recordingSeen = true;
    if (!recorder.session || retiredRecordings.has(recorder.session) || retiredRecordings.size >= 64) return replaced;
    if (!recordingLease) recordingLease = { session: recorder.session, sourcePolicy: recorder.sourcePolicy, expires: Infinity, deadline: Infinity,
      duration: 600000, maxFrames: 1200, frames: 0, closed: false };
    if (!recordingBudgetOpen()) return replaced;
    if (recorder.sourcePolicy !== recordingLease.sourcePolicy) { recordingLease.closed = true; return replaced; }
    if (recorder.sourcePolicy === "automatic-sustained") {
      // This branch has an owner heartbeat, not an observation time/frame budget. Evidence cannot renew or rearm it.
      if (recorder.status !== "capturing" || recorder.stopReason !== null || snapshot.sourceTerminalBoundary ||
          recorder.inferenceEnabled === false || snapshot.inferenceEnabled === false || ["disabled", "failed"].includes(snapshot.modelState) ||
          ["stopped", "failed", "interrupted"].includes(snapshot.automaticStartup?.status)) {
        recordingLease.stopReason = recorder.stopReason || snapshot.automaticStartup?.stopReason;
        recordingLease.closed = true;
        return replaced;
      }
      // A boot feed is not an owner claim. Service identity is immutable even before the first live feed.
      if (recordingLease.feed !== undefined && recordingLease.feed !== snapshot.session ||
          recordingLease.service && snapshot.service && recordingLease.service !== snapshot.service) {
        recordingLease.closed = true;
        return replaced;
      }
      if (snapshot.service) recordingLease.service = snapshot.service;
      const evidence = recorder.evidence;
      const previous = recordingLease.evidence;
      if (recordingLease.elapsed_ms !== undefined && recorder.elapsed_ms < recordingLease.elapsed_ms ||
          previous && (["max_duration_ms", "max_frames", "max_bytes"].some(key => previous[key] !== evidence[key]) ||
          ["elapsed_ms", "recorded_frames", "recorded_bytes"].some(key => evidence[key] < previous[key]) ||
          previous.status === "ended" && Object.keys(previous).some(key => previous[key] !== evidence[key]))) {
        recordingLease.closed = true;
        return replaced;
      }
      recordingLease.elapsed_ms = recorder.elapsed_ms;
      recordingLease.evidence = evidence;
      const updated = recorder.updated_at_unix_ms;
      if (updated > Date.now() + 500 || recordingLease.receiptHeartbeat !== undefined && updated < recordingLease.receiptHeartbeat) return replaced;
      const expires = updated + SUSTAINED_RECEIPT_MAX_MS;
      const deadline = performance.now() + Math.max(0, Math.min(SUSTAINED_RECEIPT_MAX_MS, expires - Date.now()) - roundTripMs);
      const same = updated === recordingLease.receiptHeartbeat;
      recordingLease.receiptExpires = Math.min(same ? recordingLease.receiptExpires : Infinity, expires);
      recordingLease.receiptDeadline = Math.min(same ? recordingLease.receiptDeadline : Infinity, deadline);
      recordingLease.receiptHeartbeat = updated;
      const capture = snapshot.capture;
      if (recordingLease.feed === undefined && snapshot.service && snapshot.service === recordingLease.service &&
          snapshot.source === "live" && !snapshot.sourceBoundary && snapshot.inferenceEnabled === true && snapshot.modelState === "ready" &&
          ["verifying", "active"].includes(capture.state) && capture.fresh && capture.epoch !== null &&
          capture.width !== null && capture.height !== null && capture.heartbeat !== null &&
          capture.heartbeat <= Date.now() + 500 && Date.now() - capture.heartbeat < HEARTBEAT_MAX_MS && recordingFresh()) {
        recordingLease.feed = snapshot.session;
      }
      return replaced;
    }
    if (recorder.status !== "capturing" || recorder.sourcePolicy === "automatic-bounded" &&
        ["stopped", "failed", "interrupted"].includes(snapshot.automaticStartup?.status) || ![recorder.remaining_ms, recorder.elapsed_ms, recorder.max_duration_ms,
      recorder.max_frames, recorder.recorded_frames].every(integer) || !recorder.max_duration_ms || !recorder.max_frames) {
      recordingLease.closed = true;
      return replaced;
    }
    recordingLease.duration = Math.min(recordingLease.duration, recorder.max_duration_ms);
    recordingLease.maxFrames = Math.min(recordingLease.maxFrames, recorder.max_frames);
    recordingLease.frames = Math.max(recordingLease.frames, recorder.recorded_frames);
    // remaining_ms is projected to response time. Neither repeated polls nor clock rollback may renew it.
    const remaining = Math.min(recorder.remaining_ms, recordingLease.duration - recorder.elapsed_ms) - roundTripMs;
    recordingLease.expires = Math.min(recordingLease.expires, Date.now() + Math.max(0, remaining));
    recordingLease.deadline = Math.min(recordingLease.deadline, performance.now() + Math.max(0, remaining));
    if (remaining <= 0 || recordingLease.frames >= recordingLease.maxFrames) recordingLease.closed = true;
    return replaced;
  }

  function renderSource(observation) {
    renderStopCapture();
    const capture = snapshot?.capture;
    const recorder = snapshot?.recording;
    const automatic = automaticPolicy(recorder?.sourcePolicy);
    const sustained = recorder?.sourcePolicy === "automatic-sustained";
    const activityPending = automatic && recorder?.mode === "inference-enabled" && recorder.activityState !== "active";
    const idle = recorder?.status === "idle";
    const terminal = recorder && !["idle", "capturing"].includes(recorder.status);
    const receiptFresh = recordingFresh();
    const budgetOpen = recordingBudgetOpen();
    const healthy = captureHealthy();
    text("source-status", !connected ? "Disconnected" : idle ? automatic ? ACTIVITY_LABELS.idle : "No manual session" : terminal ? `Session ${recorder.status}` :
      recorder && !receiptFresh ? "Session status stale" : recorder && !budgetOpen ? sustained ? "Session closed" : "Session budget closed" :
      sustained && healthy ? "Observing same table" :
      activityPending ? healthy ? "Source capturing / verifying table activity" : ACTIVITY_LABELS[recorder.activityState] : healthy ? automatic ? ACTIVITY_LABELS.active : "Source connected" :
      capture?.state === "blocked" ? "Source not confirmed" : recorder?.status === "capturing" ?
        recorder.mode === "capture-only" ? "Capture-only source" : `${automatic ? "Automatic" : "Manual"} capture / no current source reading` : "No current source");
    const context = currentContext();
    const roleText = context ? `${ROLE_NAMES[context.role]}${context.provisional || context.roleStatus === "provisional" ? " / provisional" : ""}` : observation ? ROLE_NAMES[observation.role] : "Role unknown";
    const role = context?.role ?? observation?.role ?? "uncertain";
    text("source-role", context || observation ? ROLE_NAMES[role] : "Role unknown");
    attribute(node("source-role"), "title", roleText);
    publishField(node("source-role"), "role", context?.role ?? observation?.role ?? "uncertain",
      context?.provisional ? "provisional" : context?.roleStatus || (observation ? "current" : "unknown"), context?.capture || originalFor(observation, "role"));
    const captureAge = !capture || capture.heartbeat === null || heartbeat !== capture.heartbeat ? null : Math.max(0, Date.now() - capture.heartbeat,
      HEARTBEAT_MAX_MS - (heartbeatDeadline - performance.now()));
    const captureCurrent = connected && (!sustained || healthy) && snapshot.source === "live" && capture?.fresh &&
      Date.now() < heartbeatExpires && performance.now() < heartbeatDeadline;
    text("capture-freshness", captureAge === null || !connected ? "No current capture" :
      captureCurrent ? "Capture current" : `Last capture ${ageSummary(captureAge)} old / not current`);
    const lastReadOnly = !observation && retainedNumbers.size > 0;
    const sourceAge = observation ? Math.max(0, Date.now() - observation.captured) : null;
    text("source-freshness", observation ? `Reading age ${ageSummary(sourceAge)}${retainedCount(observation) ? " / last-read fields individually labeled" : ""}` :
      lastReadOnly ? "Last-read amounts only / not current" : clearReason === "stale" ? "Reading expired" : "No current reading");
    text("diagnostic-timing", !connected ? "Unavailable" :
      `Capture ${captureAge === null ? "unknown" : `${count(Math.floor(captureAge))} ms`} / reading ${sourceAge === null ? "unavailable" : `${count(Math.floor(sourceAge))} ms`}${recorder ? ` / observation ${duration(recorder.elapsed_ms)}` : ""}`);
    const recorderStatus = recorder?.status === "capturing" ? !receiptFresh ? "status stale" : !budgetOpen ? "budget closed" : automatic && recorder.mode === "inference-enabled" ? `capturing / activity ${recorder.activityState}` : "capturing" : recorder?.status;
    text("recorder-status", !connected || !recorder ? "Recorder status unavailable" : idle ? automatic ? ACTIVITY_LABELS.idle : "No manual session" :
      sustained ? `Evidence recording ${recorder.evidence.status}${recorder.evidence.status === "ended" && healthy ? "; observation continues" : healthy ? "" : " / last received"}${recorder.evidence.stop_reason ? ` / ${recorder.evidence.stop_reason}` : ""}` :
        `${recorder.mode === "capture-only" ? "Capture only" : automatic ? "Automatic inference" : "Diagnostic inference"} / ${recorderStatus}`);
    let inference = "Inference status unknown";
    if (!connected) inference = "Inference status unavailable";
    else if (idle) inference = `Inference OFF${snapshot.modelState === "loading" ? " / model loading" : ""}`;
    else if (terminal) inference = `Inference OFF / session ${recorder.status}`;
    else if (recorder?.mode === "capture-only" || recorder?.inferenceEnabled === false) inference = "Inference OFF";
    else if (recorder && !receiptFresh) inference = "Inference enabled / status stale";
    else if (recorder && !budgetOpen) inference = sustained ? "Inference OFF / session closed" : "Inference OFF / session budget closed";
    else if (recorder) {
      if (snapshot.inferenceEnabled !== true) inference = `Inference unavailable / service ${snapshot.inferenceEnabled === false ? "OFF" : "unknown"}`;
      else if (snapshot.modelState !== "ready") inference = `Inference enabled / model ${snapshot.modelState}`;
      else if (activityPending) inference = `Inference enabled / ${lastReadOnly ? "last-read amounts only / no current reading" : observation && node("monitor-readings").dataset.numericReading === "current" ? "partial result" : "no admissible result"} / activity ${recorder.activityState}${snapshot.inferenceBusy ? " / busy" : ""}`;
      else inference = `Inference enabled / ${lastReadOnly ? "last-read amounts only / no current reading" : observation && node("monitor-readings").dataset.numericReading === "current" ? observation.partial ? "partial result" : "experimental result" : "no admissible result"}${snapshot.inferenceBusy ? " / busy" : ""}`;
    } else if (snapshot?.inferenceEnabled === false) inference = "Inference OFF / no session receipt";
    else if (snapshot?.modelState === "loading") inference = "Model loading / session status unknown";
    text("inference-status", inference);
    text("model-status", connected && snapshot ? `Service inference ${snapshot.inferenceEnabled === true ? "ON" : snapshot.inferenceEnabled === false ? "OFF" : "unknown"}; model ${snapshot.modelState} / ${snapshot.inferenceBusy ? "busy" : "idle"}; quality ${snapshot.qualityGate}` : "Disconnected");
    text("recorder-budget", sustained ? `Evidence ${duration(recorder.evidence.elapsed_ms)} / ${duration(recorder.evidence.max_duration_ms)}; ${count(recorder.recorded_frames)} / ${count(recorder.evidence.max_frames)} frames; ${count(recorder.recorded_bytes)} / ${count(recorder.evidence.max_bytes)} bytes` :
      recorder ? `${duration(recorder.elapsed_ms)} / ${duration(recorder.max_duration_ms)}; ${count(recorder.recorded_frames)} / ${count(recorder.max_frames)} frames` : "Default: 10 min or 1,200 frames");
    text("recorder-loss", recorder ? `${count(recorder.capture_failures)} capture failures / ${count(recorder.gap_count)} gaps; ${count(recorder.estimated_missed_samples)} estimated missed samples; max ${count(recorder.max_gap_ms)} ms` : "No session receipt");
    text("opportunity-status", recorder ? `${count(recorder.distinct_opportunities)} / ${count(recorder.target_opportunities)} draft markers; deficit ${count(recorder.opportunity_deficit)}` : "Target 20 distinct opportunities, not repeated frames");
    text("recorder-stop", recorder && !idle ? sustained ? `Sustained observation ${recorder.status}${recorder.stopReason ? `: ${recorder.stopReason}` : ""}. Evidence limits end recording only; source or owner failure stops observation. No automatic restart. Markers remain DRAFT / review PENDING.` :
      `${!connected || !terminal && (!receiptFresh || !budgetOpen) ? "Last received recorder" : "Recorder"} ${recorder.status}${recorder.stopReason ? `: ${recorder.stopReason}` : ""}. Stops at the first budget limit; no automatic restart. Markers remain DRAFT / review PENDING.` :
      `${snapshot?.captureControl?.enabled ? "Use Start monitor to request source validation; Stop monitor leaves the model warm." : automatic ? "Automatic observation is controlled by the supervisor." : "Use the manual capture terminal to confirm the source and start."} Opening this page never starts capture or inference.`);
    if (connected && recorder && !node("monitor-empty").hidden) {
      text("monitor-empty", idle ? automatic ? "Automatic observation idle. No active-table readings." : "No manual session. Start only in the capture terminal." :
        terminal ? recorder.stopReason === "table-activity-unconfirmed" ? "Table activity unconfirmed. Probe stopped; readings cleared." : `Session ${recorder.status}. Readings cleared.` :
        !receiptFresh ? "Session status stale. Readings cleared." :
        !budgetOpen ? `Session ${sustained ? "closed" : "budget closed"}. Readings cleared.` :
        recorder.mode === "capture-only" ? "Capture only. Readings are off." : !recorder.inferenceEnabled ? "Session inference is OFF. Readings are off." :
        snapshot.inferenceEnabled !== true ? "Inference service unavailable. Readings cleared." :
        snapshot.modelState !== "ready" ? `Model ${snapshot.modelState}. No table readings.` :
        activityPending ? `${healthy ? sustained ? "Observing same table / verifying table activity" : "Source capturing / verifying table activity" : ACTIVITY_LABELS[recorder.activityState]}. No independently admitted readings yet; history is not eligible.` :
        "No admissible result. See diagnostics for field reasons.");
    }
    const startup = snapshot?.automaticStartup;
    const startupOnly = startup && (!recorder || idle ||
      recorder.status !== "capturing" && ["waiting-model", "searching"].includes(startup.status) ||
      automatic && ["stopped", "failed", "interrupted"].includes(startup.status));
    if (connected && startupOnly) {
      const label = AUTOMATIC_LABELS[startup.status];
      const stopReason = startup.stopReason || (automatic && terminal ? recorder.stopReason : null);
      text("source-status", label);
      text("recorder-status", `Automatic startup / ${startup.status}`);
      text("inference-status", startup.status === "waiting-model" ? `No capture / model ${snapshot.modelState}` : "No admitted table reading");
      if (!recorder?.session || !terminal || ["waiting-model", "searching"].includes(startup.status)) {
        text("recorder-budget", "No active capture session.");
        text("recorder-loss", "No current session receipt");
      }
      text("recorder-stop", `Automatic startup ${startup.status}${stopReason ? `: ${stopReason}` : ""}. Opening or refreshing this page never starts capture or inference.`);
      text("monitor-empty", stopReason === "table-activity-unconfirmed" ? "Table activity unconfirmed. Probe stopped; readings cleared." :
        `${label}. ${startup.status === "searching" ? "Metadata only; no capture started." : "No active-table readings."}`);
    }
    const startupTerminal = automatic && ["stopped", "failed", "interrupted"].includes(startup?.status) ||
      !recorder && ["stopped", "failed", "interrupted"].includes(startup?.status);
    const starting = snapshot?.captureControl?.status === "starting";
    const recovery = !starting && !!(terminal || startupTerminal || recorder && !idle && !budgetOpen);
    node("monitor-lifecycle").hidden = !recovery;
    node("monitor-launch").hidden = !!snapshot?.captureControl?.enabled || !recovery || !automatic && !startupTerminal;
    if (connected && starting) text("source-status", ["waiting-model", "searching", "verifying", "active"].includes(startup?.status) ?
      AUTOMATIC_LABELS[startup.status] : "Starting monitor");
    if (recovery) {
      const stopReason = recorder?.stopReason || startupTerminal && startup.stopReason ||
        sustained && recordingLease?.session === recorder.session && recordingLease.stopReason;
      text("monitor-stop", `${startupTerminal ? AUTOMATIC_LABELS[startup.status] : terminal ? `Session ${recorder.status}` : sustained ? "Session closed" : "Session budget closed"}${stopReason ? `: ${stopReason}` : "; stop reason unavailable"}. Current and last-read amounts cleared.`);
      text("monitor-launch", `scripts/start-vlm.ps1 -EnableInference -AutomaticInference${sustained ? " -ContinuousObservation" : ""}`);
    }
  }

  function renderDiagnostics(observation) {
    const fields = [["Role / hero identity", "hero_seat"], ["Hero cards", "hero_cards"], ["Hero stack", "hero_chips"],
      ...Array.from({ length: 5 }, (_, index) => [`Board card ${index + 1}`, `board_slots.${index + 1}`]),
      ["Upper Pot", "pot_size"], ["Action controls", "controls"],
      ["Lower center chips", "center_chip"], ["Street contributions", "street_contribution"], ["Hand positions", "position"], ["Pot convention", "pot_convention"]];
    const fragment = document.createDocumentFragment();
    const admitted = { hero_seat: observation?.heroSeat != null, hero_cards: !!observation?.hero.length,
      hero_chips: observation?.amounts.hero_chips != null,
      ...Object.fromEntries(Array.from({ length: 5 }, (_, index) => [`board_slots.${index + 1}`, !!observation?.board[index]])),
      pot_size: observation?.amounts.pot_size != null, controls: !!observation && [...observation.controls.values()].some((v) => v.presence === "present") };
    for (const [label, key] of fields) {
      const item = make("div");
      item.append(make("dt", "", label), make("dd", "", admitted[key] ? "Admitted / experimental" : retainedNumbers.has(key) ? retainedLabel(key, true) : reasonFor(observation, key,
        ["hero_seat", "hero_cards", "hero_chips", "controls", "center_chip"].includes(key) ? "missing-capability" : "insufficient-context")));
      fragment.append(item);
    }
    node("field-diagnostics").replaceChildren(fragment);
  }

  function captureHealthy() {
    // Source health permits partial readout, not full observations or activity/history eligibility.
    const recorder = snapshot?.recording;
    return connected && snapshot && !(stopMatches() && ["requested", "unavailable"].includes(stopRequest.state)) && (!recorder ? !recordingSeen : recorder.status === "capturing" && recorder.mode === "inference-enabled" &&
      (!automaticPolicy(recorder.sourcePolicy) || ["verifying", "active"].includes(recorder.activityState) &&
        (!snapshot.automaticStartup || ["verifying", "active"].includes(snapshot.automaticStartup.status))) &&
      recorder.inferenceEnabled && snapshot.inferenceEnabled === true && snapshot.modelState === "ready" && recordingFresh() && recordingBudgetOpen()) &&
      (recorder?.sourcePolicy !== "automatic-sustained" || snapshot.service && recordingLease?.service === snapshot.service &&
        recordingLease.feed === snapshot.session && !snapshot.sourceBoundary && snapshot.capture.epoch !== null &&
        snapshot.capture.width !== null && snapshot.capture.height !== null) &&
      snapshot.source === "live" && ["verifying", "active"].includes(snapshot.capture.state) && snapshot.capture.fresh &&
      snapshot.capture.heartbeat !== null && Date.now() < heartbeatExpires && performance.now() < heartbeatDeadline;
  }

  function activityQualified() {
    return !automaticPolicy(snapshot?.recording?.sourcePolicy) || snapshot.recording.activityState === "active";
  }

  function renderHistory(value) {
    if (!activityQualified() && ["idle", "capturing"].includes(snapshot.recording.status)) value = null;
    historyEvents = value ? value.events : [];
    const visible = !!value && (historyEvents.length > 0 || value.actions !== null || value.gaps > 0 || Object.values(value.counts).some((entry) => entry !== null));
    node("history-panel").hidden = !visible;
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

  function clearObservation(reason = clearReason) {
    clearReason = reason;
    const wasActive = activeLease !== null;
    closeObservation(activeLease ? activeLease.observation : snapshot ? snapshot.observation : null);
    activeLease = null;
    if (adviceLease) closedAdviceKey = adviceLease.key;
    adviceLease = null;
    window.clearTimeout(leaseTimer);
    leaseTimer = null;
    renderObservation(null);
    if (wasActive) announce("Table reading and analysis cleared.");
  }

  function disconnected() {
    connected = false;
    clearContext();
    clearVisual();
    clearRetained();
    clearExperimental();
    recoveryAfterSequence = Math.max(recoveryAfterSequence, highestSequence);
    clearObservation("stale");
    renderHistory(snapshot ? snapshot.history : null);
    text("monitor-empty", "Table disconnected. Waiting for a fresh reading.");
    announce("Table disconnected. Analysis unavailable.");
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

  function admitAdvice(value, roundTripMs) {
    const advice = value.advice;
    const key = `${fullBinding}:${activeLease.observation.captured}`;
    const remaining = advice ? Math.min(advice.remaining - roundTripMs, advice.expires - Date.now()) : 0;
    const same = adviceLease?.key === key;
    if (!advice || key === closedAdviceKey || remaining <= 0 || advice.expires <= advice.captured ||
        same && advice.expires > adviceLease.expires) {
      if (adviceLease) closedAdviceKey = adviceLease.key;
      if (advice && remaining <= 0) closedAdviceKey = key;
      adviceLease = null;
      return;
    }
    adviceLease = { key, value: advice,
      expires: Math.min(advice.expires, activeLease.expires, same ? adviceLease.expires : Infinity),
      deadline: Math.min(performance.now() + remaining, activeLease.deadline, same ? adviceLease.deadline : Infinity) };
  }

  function admitObservation(value, previousSequence, roundTripMs) {
    const observation = fencedObservation(value.observation);
    if (!observation) {
      clearObservation();
      return;
    }
    if (value.capture.epoch !== null && observation.epoch !== value.capture.epoch) {
      clearRetained();
      closeObservation(observation);
      clearObservation("stale");
      return;
    }
    if (!observation.partial && (observation.session !== null || observation.sourceId !== null) &&
        (!value.service || observation.session !== value.session || observation.sourceId !== value.capture.sourceId ||
          observation.generation !== value.capture.generation)) {
      clearRetained();
      closeObservation(observation);
      clearObservation("stale");
      return;
    }
    if (!observation.partial && !activityQualified() || !observation.experimental || observation.generation === null || observation.epoch === null ||
        observation.captured === null || observation.expires === null || observation.remaining === null) {
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
      clearObservation("stale");
      return;
    }
    if (!captureHealthy()) {
      // A still-leased API-admitted number may be last-read only during transient source freshness loss.
      rememberNumbers(observation);
      closeObservation(observation);
      clearObservation("stale");
      return;
    }
    if (observation.analysisQualified) {
      const sameSource = fullSourceLease?.binding === fullBinding;
      const sameCapture = sameSource && observation.captured === fullSourceLease.captured;
      if (sameSource && observation.captured < fullSourceLease.captured ||
          sameCapture && (observation.expires > fullSourceLease.expires || wall >= fullSourceLease.expires || monotonic >= fullSourceLease.deadline)) {
        closeObservation(observation);
        clearObservation("stale");
        return;
      }
      // Relabeling a generation must not renew the original full-source analysis lease.
      fullSourceLease = { binding: fullBinding, captured: observation.captured, expires: observation.expires,
        deadline: Math.min(monotonic + remaining, sameCapture ? fullSourceLease.deadline : Infinity) };
    }
    // Repeated polls can only shorten a lease. A new event sequence alone cannot renew it.
    const deadline = Math.min(sameLease ? activeLease.deadline : Infinity, monotonic + remaining, recordingLease?.deadline ?? Infinity,
      observation.analysisQualified ? fullSourceLease.deadline : Infinity);
    const expires = Math.min(sameLease ? activeLease.expires : Infinity, observation.expires, recordingLease?.expires ?? Infinity);
    const previousRole = activeLease ? activeLease.observation.role : null;
    activeLease = { key, deadline, expires, observation };
    admitAdvice(value, roundTripMs);
    rememberNumbers(observation);
    clearReason = "insufficient-context";
    observationFloor = { epoch: observation.epoch, generation: observation.generation };
    closedLeaseKey = null;
    window.clearTimeout(leaseTimer);
    leaseTimer = window.setTimeout(refreshClocks, Math.max(0, Math.min(deadline - monotonic, expires - wall,
      adviceLease ? adviceLease.deadline - monotonic : Infinity, adviceLease ? adviceLease.expires - wall : Infinity)) + 1);
    renderObservation(observation);
    if (previousRole !== observation.role) announce(adviceLease ? "Experimental recommendation available; model quality is not approved." : ROLE_MESSAGES[observation.role]);
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
    const binding = [value.service, value.session, value.recording?.session, value.capture.sourceId,
      value.capture.epoch, value.capture.width, value.capture.height].join("|");
    const changedFullSource = fullBinding !== null && fullBinding !== binding &&
      (activeLease?.observation.analysisQualified || adviceLease !== null);
    fullBinding = binding;
    if (changedSession) clearRetained();
    if (changedSession) { clearExperimental(); experimentalFloor = experimentalClosedKey = experimentalBinding = null; }
    const changedArm = snapshot?.service === value.service && snapshot?.captureControl && value.captureControl &&
      snapshot.captureControl.id !== value.captureControl.id;
    if (changedArm) {
      // A new explicit arm may recover; receipts from its retired predecessor never do.
      if (snapshot.recording?.session) retiredRecordings.add(snapshot.recording.session);
      recordingLease = null;
      clearObservation();
      observationFloor = closedLeaseKey = fullSourceLease = null;
      clearExperimental(); experimentalFloor = experimentalClosedKey = experimentalBinding = null;
    }
    snapshot = value;
    if (startRequest && !startMatches()) {
      if (startController) startController.abort();
      startController = null;
      startRequest = null;
    }
    if (stopRequest && !stopMatches()) {
      if (stopController) stopController.abort();
      stopController = null;
      stopRequest = null;
    }
    connected = true;
    if (value.automaticStartup) recordingSeen = true;
    const changedRecording = updateRecordingLease(value.recording, roundTripMs) || changedArm;
    if (changedRecording) clearRetained();
    updateHeartbeat(value);
    const changedSource = updateRetainedScope();
    admitExperimental(value, previousSequence, roundTripMs, changedSession || changedRecording || changedSource || value.sourceBoundary);
    admitVisual(value, roundTripMs);
    admitContext(value, roundTripMs, changedSession || changedRecording || changedSource || value.sourceBoundary);
    admitNumeric(value, roundTripMs);
    renderHistory(value.history);
    if (changedSession || changedRecording || changedSource || changedFullSource || value.sourceBoundary) {
      closeObservation(value.observation);
      clearObservation();
    } else admitObservation(value, previousSequence, roundTripMs);
    if (connectionChanged && !activeLease) announce("Waiting for a current table reading and analysis.");
    refreshClocks();
  }

  function refreshClocks() {
    if (!connected || !snapshot || document.hidden) return;
    const wall = Date.now();
    const monotonic = performance.now();
    if (contextLease && (wall >= contextLease.expires || monotonic >= contextLease.deadline || !captureHealthy())) clearContext();
    if (visualLease && (wall >= visualLease.value.expires || monotonic >= visualLease.deadline || !captureHealthy())) clearVisual();
    if (numericLease && (wall >= numericLease.value.expires || monotonic >= numericLease.deadline || !captureHealthy())) numericLease = null;
    if (experimentalLease) {
      if (!experimentalAllowed() || wall >= experimentalLease.expires || monotonic >= experimentalLease.deadline) clearExperimental();
      else renderExperimental();
    }
    if (adviceLease && (wall >= adviceLease.expires || monotonic >= adviceLease.deadline)) {
      closedAdviceKey = adviceLease.key;
      adviceLease = null;
      renderAction(activeLease?.observation || null);
    }
    updateRetainedScope();
    if (activeLease && !captureHealthy()) clearObservation("stale");
    if (activeLease && (wall >= activeLease.expires || monotonic >= activeLease.deadline)) {
      clearObservation("stale");
    }
    renderObservation(activeLease?.observation || null);
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
    if (startController) startController.abort();
    startController = null;
    startRequest = null;
    if (stopController) stopController.abort();
    stopController = null;
    stopRequest = null;
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
    const labels = { monitor: "Experimental readings and analysis", reference: "Local reference / not live guidance" };
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
        const detail = make("article", "reference-section");
        detail.dataset.sectionId = section.id;
        detail.id = `reference-${section.id}`;
        const summary = make("h3", "", section.title);
        summary.tabIndex = -1;
        const topic = make("button", "topic-button");
        topic.type = "button";
        topic.setAttribute("aria-controls", detail.id);
        const number = make("span", "reference-number", String(index + 1).padStart(2, "0"));
        number.setAttribute("aria-hidden", "true");
        topic.append(number, make("span", "", section.title));
        topic.addEventListener("click", () => { selectedTopic = section.id; filterReference(); });
        node("reference-topics").append(topic);
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
        rendered.push({ detail, topic, id: section.id, searchText });
      }
      node("reference-sections").replaceChildren(fragment);
      referenceSections = rendered;
      text("reference-title", value.title);
      text("reference-scope", "Offline study / not current-hand guidance");
      node("reference-scope").title = value.scope;
      text("reference-reviewed", `Reviewed ${new Date(value.reviewed).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`);
      node("reference-search").disabled = false;
      node("reference-load-status").hidden = true;
      referenceLoaded = true;
      filterReference();
    } catch {
      referenceSections = [];
      node("reference-topics").replaceChildren();
      node("reference-sections").replaceChildren();
      node("reference-search").disabled = true;
      node("reference-load-status").hidden = false;
      status("reference-load-status", "Local reference could not be read. No facts have been substituted.", "warning");
    }
  }

  function filterReference() {
    const words = node("reference-search").value.slice(0, 160).normalize("NFKC").toLowerCase().trim().split(/\s+/).filter(Boolean);
    const matching = referenceSections.filter((entry) => words.every((word) => entry.searchText.includes(word)));
    if (!matching.some((entry) => entry.id === selectedTopic)) selectedTopic = matching[0]?.id || null;
    for (const entry of referenceSections) {
      entry.topic.hidden = !matching.includes(entry);
      entry.topic.setAttribute("aria-current", String(entry.id === selectedTopic));
      entry.detail.hidden = entry.id !== selectedTopic;
    }
    const matches = matching.length;
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
  node("start-capture").addEventListener("click", startCapture);
  node("stop-capture").addEventListener("click", stopCapture);
  node("close-player-details").addEventListener("click", closePlayerDetails);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && selectedSeat !== null) { event.preventDefault(); closePlayerDetails(); }
  });
  node("reference-search").addEventListener("input", filterReference);
  document.addEventListener("visibilitychange", () => document.hidden ? suspend() : resume());
  window.addEventListener("pagehide", suspend);
  window.addEventListener("pageshow", (event) => { if (event.persisted && !document.hidden) resume(); });
  window.coinpokerMonitor = Object.freeze({ renderReceipts: () => ({ schema_version: 1, capacity: RENDER_RECEIPT_LIMIT,
    dropped: droppedRenderReceipts, clock_origins: { publication_unix: "browser Date.now UTC milliseconds",
      publication_monotonic: "browser performance.now milliseconds", browser_time_origin_unix_ms: performance.timeOrigin ?? null,
      capture_monotonic: "producer clock; not comparable to browser monotonic" },
    receipts: renderReceipts.map(receipt => ({ ...receipt, capture: receipt.capture ? { ...receipt.capture } : null })) }) });
  window.monitorRenderReceipts = Object.freeze({ read: window.coinpokerMonitor.renderReceipts,
    reset: () => { renderReceipts.length = 0; droppedRenderReceipts = 0; } });
  renderObservation(null);
  clearExperimental();
  renderHistory(null);
  window.setInterval(refreshClocks, 100);
  if (!document.hidden) schedulePoll(0);
})();
