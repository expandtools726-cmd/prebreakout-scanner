<?php
/**
 * Isko server par "refresh_config.php" naam se copy karo (GoogieHost File Manager mein), phir values bharo.
 * Ye file GitHub repo mein MAT daalna, isme token aur password hota hai.
 *
 * password_hash banane ke liye (apne PC/phone par kisi PHP sandbox mein) ya Python se:
 *   Python:  pip install bcrypt ; python -c "import bcrypt;print(bcrypt.hashpw(b'APNA_PASSWORD', bcrypt.gensalt(prefix=b'2y')).decode())"
 *   PHP:     echo password_hash('APNA_PASSWORD', PASSWORD_DEFAULT);
 */
return [
    // GitHub fine-grained token: sirf is repo par, permission "Actions: Read and write"
    'token'         => 'github_pat_XXXXXXXXXXXXXXXX',
    'repo'          => 'AAPKA_GITHUB_USERNAME/prebreakout-scanner',
    'workflow'      => 'scan.yml',
    'ref'           => 'main',
    'password_hash' => '$2y$10$........................................................',
];
