import sys
import itertools
import multiprocessing as mp
from typing import Optional, Iterator, List
from collections import Counter
from functools import partial

import pyzipper
from tqdm import tqdm

# --- Конфигурация ---
BASE_WORDS = ["0"]
SYMBOLS = ['!', '_', '@']
DIGIT_LENGTHS = [7]#[4, 6]
FILTER_DIGITS = True
MAX_UPPER = 2
BAD_DIGITS = '124569'
BATCH_SIZE = 5000


def generate_case_variants(word: str, max_upper: int = MAX_UPPER) -> List[str]:
    variants = []
    n = len(word)
    for mask in range(1 << n):
        if bin(mask).count('1') > max_upper:
            continue
        variants.append(''.join(
            word[i].upper() if (mask >> i) & 1 else word[i].lower()
            for i in range(n)
        ))
    return set(variants)


def is_valid_digit_block(digits: str) -> bool:
    if not FILTER_DIGITS:
        return True
    # if digits[0] == '0':
    #     return False
    counts = Counter(digits)
    if max(counts.values()) > 3:
        return False
    if len(counts) < 3:
        return False
    for i in range(len(digits) - 2):
        if digits[i] == digits[i + 1] == digits[i + 2]:
            return False
    return True


def generate_digit_blocks(alphabet: str, lengths: List[int]) -> Iterator[str]:
    for length in lengths:
        for tup in itertools.product(alphabet, repeat=length):
            s = ''.join(tup)
            if is_valid_digit_block(s):
                yield s


def generate_digit_blocks_with_bad(full_alphabet: str, bad: str, lengths: List[int]) -> Iterator[str]:
    for length in lengths:
        for tup in itertools.product(full_alphabet, repeat=length):
            s = ''.join(tup)
            if not any(c in bad for c in s):
                continue
            if is_valid_digit_block(s):
                yield s


def password_generator(letter_variants: List[str]) -> Iterator[str]:
    alphabet_full = '0123456789'
    alphabet_good = ''.join(a for a in alphabet_full if a not in BAD_DIGITS)

    for digits in generate_digit_blocks(alphabet_good, DIGIT_LENGTHS):
        for letters in letter_variants:
            yield letters + digits
            for sym in SYMBOLS:
                yield sym + letters + digits
            for sym in SYMBOLS:
                yield letters + sym + digits
            for sym in SYMBOLS:
                yield letters + digits + sym
            if letters:
                yield digits + letters
                for sym in SYMBOLS:
                    yield sym + digits + letters
                for sym in SYMBOLS:
                    yield digits + sym + letters
                for sym in SYMBOLS:
                    yield digits + letters + sym

    for digits in generate_digit_blocks_with_bad(alphabet_full, BAD_DIGITS, DIGIT_LENGTHS):
        for letters in letter_variants:
            yield letters + digits
            for sym in SYMBOLS:
                yield sym + letters + digits
            for sym in SYMBOLS:
                yield letters + sym + digits
            for sym in SYMBOLS:
                yield letters + digits + sym
            if letters:
                yield digits + letters
                for sym in SYMBOLS:
                    yield sym + digits + letters
                for sym in SYMBOLS:
                    yield digits + sym + letters
                for sym in SYMBOLS:
                    yield digits + letters + sym


def check_batch(batch: List[str], zip_path: str) -> Optional[str]:
    try:
        with pyzipper.AESZipFile(zip_path) as zf:
            for pwd in batch:
                try:
                    zf.setpassword(pwd.encode('utf-8'))
                    files = zf.namelist()
                    if files:
                        zf.read(files[0])
                    else:
                        zf.extractall(pwd=pwd.encode('utf-8'))
                    return pwd
                except Exception:
                    continue
    except Exception as e:
        print(f"Ошибка открытия архива: {e}")
        return None
    return None


def batch_generator(iterable, batch_size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def crack_zip_parallel(zip_path: str, num_processes: Optional[int] = None) -> Optional[str]:
    letter_variants = []
    for word in BASE_WORDS:
        letter_variants.extend(generate_case_variants(word))
    print(f"Количество буквенных вариантов: {len(letter_variants)}")

    if num_processes is None:
        num_processes = mp.cpu_count()
    print(f"Используется процессов: {num_processes}")

    pwd_iter = password_generator(letter_variants)
    batches = batch_generator(pwd_iter, BATCH_SIZE)

    check_func = partial(check_batch, zip_path=zip_path)

    with mp.Pool(processes=num_processes) as pool:
        with tqdm(desc="Перебор батчей", unit="batch") as pbar:
            for result in pool.imap_unordered(check_func, batches):
                pbar.update(1)
                if result is not None:
                    pool.terminate()
                    return result
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python cracker.py <путь_к_архиву.zip>")
        sys.exit(1)

    found = crack_zip_parallel(sys.argv[1])
    if found:
        print(f"\n✅ Пароль найден: {found}")
    else:
        print("\n❌ Пароль не найден.")