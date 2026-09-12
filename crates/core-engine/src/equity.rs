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
            let best = ranks.iter().max().copied().expect("at least one hand");
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
        // Board: four hearts; hero holds the ace of hearts for the nut flush.
        // The villain can only win by making a full house with a pocket pair
        // matching a board card (~0.3%), so hero equity is near-certain.
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
}
