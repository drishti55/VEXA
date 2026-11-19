document.addEventListener('DOMContentLoaded', () => {
    const rockBtn = document.getElementById('rockBtn');
    const paperBtn = document.getElementById('paperBtn');
    const scissorsBtn = document.getElementById('scissorsBtn');
    const resultDiv = document.getElementById('result');
    const userScoreSpan = document.getElementById('userScore');
    const computerScoreSpan = document.getElementById('computerScore');
    const tieScoreSpan = document.getElementById('tieScore');
    const resetBtn = document.getElementById('resetBtn');

    let userScore = 0;
    let computerScore = 0;
    let tieScore = 0;

    const choices = ['Rock', 'Paper', 'Scissors'];

    function getComputerChoice() {
        const randomIndex = Math.floor(Math.random() * choices.length);
        return choices[randomIndex];
    }

    function determineWinner(userChoice, computerChoice) {
        if (userChoice === computerChoice) {
            return 'tie';
        }

        if (
            (userChoice === 'Rock' && computerChoice === 'Scissors') ||
            (userChoice === 'Paper' && computerChoice === 'Rock') ||
            (userChoice === 'Scissors' && computerChoice === 'Paper')
        ) {
            return 'user';
        }

        return 'computer';
    }

    function updateScore(winner) {
        if (winner === 'user') {
            userScore++;
            userScoreSpan.textContent = userScore;
        } else if (winner === 'computer') {
            computerScore++;
            computerScoreSpan.textContent = computerScore;
        } else {
            tieScore++;
            tieScoreSpan.textContent = tieScore;
        }
    }

    function playGame(userChoice) {
        const computerChoice = getComputerChoice();
        const winner = determineWinner(userChoice, computerChoice);
        
        updateScore(winner);

        if (winner === 'user') {
            resultDiv.textContent = `You win! ${userChoice} beats ${computerChoice}.`;
            resultDiv.style.color = '#10b981';
        } else if (winner === 'computer') {
            resultDiv.textContent = `You lose! ${computerChoice} beats ${userChoice}.`;
            resultDiv.style.color = '#ef4444';
        } else {
            resultDiv.textContent = `It's a tie! You both chose ${userChoice}.`;
            resultDiv.style.color = '#e2e8f0';
        }
    }

    rockBtn.addEventListener('click', () => playGame('Rock'));
    paperBtn.addEventListener('click', () => playGame('Paper'));
    scissorsBtn.addEventListener('click', () => playGame('Scissors'));

    resetBtn.addEventListener('click', () => {
        userScore = 0;
        computerScore = 0;
        tieScore = 0;
        userScoreSpan.textContent = userScore;
        computerScoreSpan.textContent = computerScore;
        tieScoreSpan.textContent = tieScore;
        resultDiv.textContent = 'Game reset. Make your choice!';
        resultDiv.style.color = '#e2e8f0';
    });
});
