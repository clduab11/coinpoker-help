//! Monte Carlo equity estimation via `rs_poker`.
//!
//! Estimates hero equity against opponent hands for multi-way pots with a
//! known board by dealing out the remaining cards and evaluating 7-card
//! hands with `rs_poker`'s battle-tested ranker.

use rand::seq::SliceRandom;
use rand::SeedableRng;
use thiserror::Error;

use rs_poker::core::{Card as RsCard, Hand, Rankable, Suit as RsSuit, Value as RsValue};

/// Errors produced by the equity estimator.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum EquityError {
    /// No player hands were provided.
    #[error("at least one hand is required")]
    EmptyHands,
    /// No unknown active opponents were requested.
    #[error("at least one opponent is required")]
    NoOpponents,
    /// The estimator was configured with no Monte Carlo iterations.
    #[error("equity estimation requires at least one iteration")]
    ZeroIterations,
    /// A card was specified more than once.
    #[error("duplicate card in known cards")]
    DuplicateCard,
    /// Not enough cards remain in the deck to complete the simulation.
    #[error("too many known cards for the deck")]
    DeckExhausted,
    /// A hand does not contain exactly two hole cards.
    #[error("each hand must contain exactly two hole cards")]
    InvalidHandSize,
    /// The board contains more than five cards.
    #[error("board cannot contain more than five cards")]
    BoardTooLarge,
}

/// Card rank, ordered Two..Ace.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Rank {
    Two,
    Three,
    Four,
    Five,
    Six,
    Seven,
    Eight,
    Nine,
    Ten,
    Jack,
    Queen,
    King,
    Ace,
}

impl From<Rank> for RsValue {
    fn from(r: Rank) -> Self {
        match r {
            Rank::Two => RsValue::Two,
            Rank::Three => RsValue::Three,
            Rank::Four => RsValue::Four,
            Rank::Five => RsValue::Five,
            Rank::Six => RsValue::Six,
            Rank::Seven => RsValue::Seven,
            Rank::Eight => RsValue::Eight,
            Rank::Nine => RsValue::Nine,
            Rank::Ten => RsValue::Ten,
            Rank::Jack => RsValue::Jack,
            Rank::Queen => RsValue::Queen,
            Rank::King => RsValue::King,
            Rank::Ace => RsValue::Ace,
        }
    }
}

/// Card suit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Suit {
    Spades,
    Hearts,
    Diamonds,
    Clubs,
}

impl From<Suit> for RsSuit {
    fn from(s: Suit) -> Self {
        match s {
            Suit::Spades => RsSuit::Spade,
            Suit::Hearts => RsSuit::Heart,
            Suit::Diamonds => RsSuit::Diamond,
            Suit::Clubs => RsSuit::Club,
        }
    }
}

/// A playing card.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Card {
    pub rank: Rank,
    pub suit: Suit,
}

impl Card {
    pub fn new(rank: Rank, suit: Suit) -> Self {
        Self { rank, suit }
    }

    fn to_rs(self) -> RsCard {
        RsCard::new(self.rank.into(), self.suit.into())
    }
}

/// A full 52-card deck.
fn full_deck() -> Vec<Card> {
    let ranks = [
        Rank::Two,
        Rank::Three,
        Rank::Four,
        Rank::Five,
        Rank::Six,
        Rank::Seven,
        Rank::Eight,
        Rank::Nine,
        Rank::Ten,
        Rank::Jack,
        Rank::Queen,
        Rank::King,
        Rank::Ace,
    ];
    let suits = [Suit::Spades, Suit::Hearts, Suit::Diamonds, Suit::Clubs];
    ranks
        .iter()
        .flat_map(|&r| suits.iter().map(move |&s| Card::new(r, s)))
        .collect()
}

/// Configuration for the equity estimator.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EquityConfig {
    /// Number of Monte Carlo iterations per estimate.
    pub iterations: usize,
}

impl Default for EquityConfig {
    fn default() -> Self {
        Self { iterations: 10_000 }
    }
}

/// Board-aware Monte Carlo equity estimator.
#[derive(Debug, Clone)]
pub struct EquityEstimator {
    config: EquityConfig,
}

impl EquityEstimator {
    pub fn new(config: EquityConfig) -> Self {
        Self { config }
    }

    /// Estimate hero equity against opponent hole cards given a board.
    ///
    /// `hands` contains the hero's two hole cards first, followed by each
    /// opponent's two hole cards. The board may hold 0..=5 cards; remaining
    /// board cards are dealt randomly each iteration.
    ///
    /// Returns each player's equity share in the same order as `hands`.
    pub fn estimate(&self, hands: &[Vec<Card>], board: &[Card]) -> Result<Vec<f64>, EquityError> {
        if hands.is_empty() {
            return Err(EquityError::EmptyHands);
        }
        if self.config.iterations == 0 {
            return Err(EquityError::ZeroIterations);
        }
        if board.len() > 5 {
            return Err(EquityError::BoardTooLarge);
        }
        for hand in hands {
            if hand.len() != 2 {
                return Err(EquityError::InvalidHandSize);
            }
        }

        // Collect known cards and reject duplicates.
        let mut known: Vec<Card> = Vec::with_capacity(hands.len() * 2 + board.len());
        for hand in hands {
            known.extend_from_slice(hand);
        }
        known.extend_from_slice(board);
        for i in 0..known.len() {
            for j in (i + 1)..known.len() {
                if known[i] == known[j] {
                    return Err(EquityError::DuplicateCard);
                }
            }
        }

        // Remaining deck.
        let mut deck: Vec<RsCard> = full_deck()
            .into_iter()
            .filter(|c| !known.contains(c))
            .map(Card::to_rs)
            .collect();

        let board_needed = 5 - board.len();
        if deck.len() < board_needed {
            return Err(EquityError::DeckExhausted);
        }

        let mut rng = rand::rngs::StdRng::from_entropy();
        let mut wins = vec![0u64; hands.len()];
        let mut split = vec![0.0f64; hands.len()];

        let board_rs: Vec<RsCard> = board.iter().copied().map(Card::to_rs).collect();
        let hands_rs: Vec<Vec<RsCard>> = hands
            .iter()
            .map(|h| h.iter().copied().map(Card::to_rs).collect())
            .collect();

        for _ in 0..self.config.iterations {
            deck.shuffle(&mut rng);

            // Complete the board with the first cards of the shuffled deck.
            let mut full_board = board_rs.clone();
            full_board.extend(deck.iter().take(board_needed).copied());

            // Evaluate each 7-card hand (known hole cards + full board).
            let ranks: Vec<rs_poker::core::Rank> = hands_rs
                .iter()
                .map(|hole| {
                    let mut seven = Hand::new();
                    for c in full_board.iter().chain(hole.iter()) {
                        seven.insert(*c);
                    }
                    seven.rank()
                })
                .collect();

            // Best rank wins; ties split the pot evenly.
            let best = ranks.iter().max().copied().ok_or(EquityError::EmptyHands)?;
            let tied: Vec<usize> = ranks
                .iter()
                .enumerate()
                .filter(|(_, r)| **r == best)
                .map(|(i, _)| i)
                .collect();
            if tied.len() == 1 {
                wins[tied[0]] += 1;
            } else {
                let share = 1.0 / tied.len() as f64;
                for i in tied {
                    split[i] += share;
                }
            }
        }

        let iters = self.config.iterations as f64;
        Ok(wins
            .iter()
            .zip(split.iter())
            .map(|(&w, &s)| (w as f64 + s) / iters)
            .collect())
    }

    /// Estimate hero equity against uniformly random unknown opponent hands.
    ///
    /// Each iteration shuffles the deck remaining after the hero's two cards
    /// and the known board, then deals distinct two-card hands to
    /// `opponent_count` active opponents and completes the board. The returned
    /// value is the hero's pot share, including split pots.
    pub fn estimate_against_unknown(
        &self,
        hero: &[Card],
        opponent_count: usize,
        board: &[Card],
    ) -> Result<f64, EquityError> {
        if hero.len() != 2 {
            return Err(EquityError::InvalidHandSize);
        }
        if opponent_count == 0 {
            return Err(EquityError::NoOpponents);
        }
        if self.config.iterations == 0 {
            return Err(EquityError::ZeroIterations);
        }
        if board.len() > 5 {
            return Err(EquityError::BoardTooLarge);
        }

        let mut known = Vec::with_capacity(hero.len() + board.len());
        known.extend_from_slice(hero);
        known.extend_from_slice(board);
        for i in 0..known.len() {
            for j in (i + 1)..known.len() {
                if known[i] == known[j] {
                    return Err(EquityError::DuplicateCard);
                }
            }
        }

        let mut deck: Vec<RsCard> = full_deck()
            .into_iter()
            .filter(|card| !known.contains(card))
            .map(Card::to_rs)
            .collect();
        let board_needed = 5 - board.len();
        let cards_needed = opponent_count
            .checked_mul(2)
            .and_then(|hole_cards| hole_cards.checked_add(board_needed))
            .ok_or(EquityError::DeckExhausted)?;
        if deck.len() < cards_needed {
            return Err(EquityError::DeckExhausted);
        }

        let hero_rs: Vec<RsCard> = hero.iter().copied().map(Card::to_rs).collect();
        let board_rs: Vec<RsCard> = board.iter().copied().map(Card::to_rs).collect();
        let mut rng = rand::rngs::StdRng::from_entropy();
        let mut hero_share = 0.0;

        for _ in 0..self.config.iterations {
            deck.shuffle(&mut rng);

            let mut full_board = board_rs.clone();
            full_board.extend(deck.iter().take(board_needed).copied());

            let mut hero_hand = Hand::new();
            for card in full_board.iter().chain(hero_rs.iter()) {
                hero_hand.insert(*card);
            }
            let hero_rank = hero_hand.rank();
            let mut best_rank = hero_rank;
            let mut tied_players = 1usize;
            let mut hero_has_best_rank = true;

            for opponent_index in 0..opponent_count {
                let hole_start = board_needed + opponent_index * 2;
                let hole_end = hole_start + 2;
                let mut opponent_hand = Hand::new();
                for card in full_board.iter().chain(deck[hole_start..hole_end].iter()) {
                    opponent_hand.insert(*card);
                }
                let opponent_rank = opponent_hand.rank();

                if opponent_rank > best_rank {
                    best_rank = opponent_rank;
                    tied_players = 1;
                    hero_has_best_rank = false;
                } else if opponent_rank == best_rank {
                    tied_players += 1;
                }
            }

            if hero_has_best_rank {
                hero_share += 1.0 / tied_players as f64;
            }
        }

        Ok(hero_share / self.config.iterations as f64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hand(r1: Rank, s1: Suit, r2: Rank, s2: Suit) -> Vec<Card> {
        vec![Card::new(r1, s1), Card::new(r2, s2)]
    }

    fn estimator() -> EquityEstimator {
        EquityEstimator::new(EquityConfig { iterations: 2_000 })
    }

    #[test]
    fn aces_dominate_kings_preflop() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let villain = hand(Rank::King, Suit::Clubs, Rank::King, Suit::Diamonds);
        let eq = estimator()
            .estimate(&[hero, villain], &[])
            .expect("estimate");
        // AA vs KK is roughly 82% / 18%.
        assert!(eq[0] > 0.75 && eq[0] < 0.9, "hero equity was {}", eq[0]);
        assert!((eq[0] + eq[1] - 1.0).abs() < 1e-6);
    }

    #[test]
    fn made_flush_beats_pair_on_river() {
        // On this fixed river board, the hero's ace-high heart flush always
        // beats the villain's two pair (kings and twos).
        let board = vec![
            Card::new(Rank::Two, Suit::Hearts),
            Card::new(Rank::Seven, Suit::Hearts),
            Card::new(Rank::Nine, Suit::Hearts),
            Card::new(Rank::Jack, Suit::Hearts),
            Card::new(Rank::Two, Suit::Clubs),
        ];
        let hero = hand(Rank::Ace, Suit::Hearts, Rank::Three, Suit::Spades);
        let villain = hand(Rank::King, Suit::Clubs, Rank::King, Suit::Diamonds);
        let eq = estimator()
            .estimate(&[hero, villain], &board)
            .expect("estimate");
        assert!(eq[0] > 0.99, "hero equity was {}", eq[0]);
    }

    #[test]
    fn rejects_empty_hands() {
        assert_eq!(estimator().estimate(&[], &[]), Err(EquityError::EmptyHands));
    }

    #[test]
    fn rejects_zero_iterations() {
        let estimator = EquityEstimator::new(EquityConfig { iterations: 0 });
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        assert_eq!(
            estimator.estimate(&[hero], &[]),
            Err(EquityError::ZeroIterations)
        );
    }

    #[test]
    fn rejects_duplicate_cards() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let villain = hand(Rank::Ace, Suit::Spades, Rank::King, Suit::Diamonds);
        assert_eq!(
            estimator().estimate(&[hero, villain], &[]),
            Err(EquityError::DuplicateCard)
        );
    }

    #[test]
    fn rejects_invalid_hand_size() {
        let hero = vec![Card::new(Rank::Ace, Suit::Spades)];
        let villain = hand(Rank::King, Suit::Clubs, Rank::King, Suit::Diamonds);
        assert_eq!(
            estimator().estimate(&[hero, villain], &[]),
            Err(EquityError::InvalidHandSize)
        );
    }

    #[test]
    fn rejects_board_larger_than_five() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let villain = hand(Rank::King, Suit::Clubs, Rank::King, Suit::Diamonds);
        let board = vec![
            Card::new(Rank::Two, Suit::Hearts),
            Card::new(Rank::Three, Suit::Hearts),
            Card::new(Rank::Four, Suit::Hearts),
            Card::new(Rank::Five, Suit::Hearts),
            Card::new(Rank::Six, Suit::Hearts),
            Card::new(Rank::Seven, Suit::Hearts),
        ];
        assert_eq!(
            estimator().estimate(&[hero, villain], &board),
            Err(EquityError::BoardTooLarge)
        );
    }

    #[test]
    fn multiway_equities_sum_to_one() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::King, Suit::Spades);
        let v1 = hand(Rank::Queen, Suit::Clubs, Rank::Queen, Suit::Diamonds);
        let v2 = hand(Rank::Nine, Suit::Hearts, Rank::Eight, Suit::Hearts);
        let eq = estimator()
            .estimate(&[hero, v1, v2], &[])
            .expect("estimate");
        let sum: f64 = eq.iter().sum();
        assert!((sum - 1.0).abs() < 1e-6, "sum was {sum}");
    }

    #[test]
    fn hero_with_exclusive_royal_flush_beats_unknown_opponents() {
        let hero = hand(Rank::Ten, Suit::Spades, Rank::Three, Suit::Clubs);
        let board = vec![
            Card::new(Rank::Ace, Suit::Spades),
            Card::new(Rank::King, Suit::Spades),
            Card::new(Rank::Queen, Suit::Spades),
            Card::new(Rank::Jack, Suit::Spades),
            Card::new(Rank::Two, Suit::Diamonds),
        ];
        let equity = estimator()
            .estimate_against_unknown(&hero, 4, &board)
            .expect("estimate");
        assert!((equity - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn board_royal_flush_splits_unknown_multiway_pot() {
        let hero = hand(Rank::Two, Suit::Hearts, Rank::Three, Suit::Diamonds);
        let board = vec![
            Card::new(Rank::Ace, Suit::Spades),
            Card::new(Rank::King, Suit::Spades),
            Card::new(Rank::Queen, Suit::Spades),
            Card::new(Rank::Jack, Suit::Spades),
            Card::new(Rank::Ten, Suit::Spades),
        ];
        let equity = estimator()
            .estimate_against_unknown(&hero, 3, &board)
            .expect("estimate");
        assert!((equity - 0.25).abs() < f64::EPSILON);
    }

    #[test]
    fn unknown_opponents_require_two_hero_cards() {
        let hero = vec![Card::new(Rank::Ace, Suit::Spades)];
        assert_eq!(
            estimator().estimate_against_unknown(&hero, 1, &[]),
            Err(EquityError::InvalidHandSize)
        );
    }

    #[test]
    fn unknown_opponents_require_at_least_one_opponent() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        assert_eq!(
            estimator().estimate_against_unknown(&hero, 0, &[]),
            Err(EquityError::NoOpponents)
        );
    }

    #[test]
    fn unknown_opponents_reject_zero_iterations() {
        let estimator = EquityEstimator::new(EquityConfig { iterations: 0 });
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        assert_eq!(
            estimator.estimate_against_unknown(&hero, 1, &[]),
            Err(EquityError::ZeroIterations)
        );
    }

    #[test]
    fn unknown_opponents_reject_duplicate_known_cards() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let board = vec![Card::new(Rank::Ace, Suit::Spades)];
        assert_eq!(
            estimator().estimate_against_unknown(&hero, 1, &board),
            Err(EquityError::DuplicateCard)
        );
    }

    #[test]
    fn unknown_opponents_reject_oversized_board() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let board = vec![
            Card::new(Rank::Two, Suit::Hearts),
            Card::new(Rank::Three, Suit::Hearts),
            Card::new(Rank::Four, Suit::Hearts),
            Card::new(Rank::Five, Suit::Hearts),
            Card::new(Rank::Six, Suit::Hearts),
            Card::new(Rank::Seven, Suit::Hearts),
        ];
        assert_eq!(
            estimator().estimate_against_unknown(&hero, 1, &board),
            Err(EquityError::BoardTooLarge)
        );
    }

    #[test]
    fn unknown_opponents_reject_insufficient_deck_capacity() {
        let hero = hand(Rank::Ace, Suit::Spades, Rank::Ace, Suit::Hearts);
        let board = vec![
            Card::new(Rank::Two, Suit::Hearts),
            Card::new(Rank::Three, Suit::Hearts),
            Card::new(Rank::Four, Suit::Hearts),
            Card::new(Rank::Five, Suit::Hearts),
            Card::new(Rank::Six, Suit::Hearts),
        ];
        assert_eq!(
            estimator().estimate_against_unknown(&hero, 23, &board),
            Err(EquityError::DeckExhausted)
        );
        assert_eq!(
            estimator().estimate_against_unknown(&hero, usize::MAX, &board),
            Err(EquityError::DeckExhausted)
        );
    }
}
