import random

random.seed(42)  # Initialize the random number generator

# Weighted probability of consonants based on English lexicon
base_consonant_weights = {
    "b": 0.02, "c": 0.03, "d": 0.04, "f": 0.02, "g": 0.02, "h": 0.06, "j": 0.01, "k": 0.01,
    "l": 0.04, "m": 0.03, "n": 0.05, "p": 0.02, "q": 0.001, "r": 0.06, "s": 0.06,
    "t": 0.09, "v": 0.01, "w": 0.02, "x": 0.001, "y": 0.02, "z": 0.001
}

consonant_weights = {
    "b": 0.02, "c": 0.03, "d": 0.04, "f": 0.02, "g": 0.02, "h": 0.06, "j": 0.01, "k": 0.01,
    "l": 0.04, "m": 0.03, "n": 0.05, "p": 0.02, "q": 0.001, "r": 0.06, "s": 0.06,
    "t": 0.09, "v": 0.01, "w": 0.02, "x": 0.001, "y": 0.02, "z": 0.001,
    "bh": 0.001, "ch": 0.01, "dh": 0.001, "gh": 0.001, "kh": 0.001, "ph": 0.001, "rh": 0.001,
    "sh": 0.01, "th": 0.02, "wh": 0.001, "zh": 0.001,
    "bl": 0.001, "cl": 0.001, "dl": 0.001, "fl": 0.001, "gl": 0.001, "kl": 0.001, "ll": 0.001, "pl": 0.001, "sl": 0.001, "tl": 0.001,
    "br": 0.001, "cr": 0.001, "dr": 0.001, "fr": 0.001, "gr": 0.001, "kr": 0.001, "pr": 0.001, "sr": 0.001, "tr": 0.001,
    "by": 0.001, "cy": 0.001, "dy": 0.001, "fy": 0.001, "gy": 0.001, "hy": 0.001, "ky": 0.001, "my": 0.001, "ny": 0.001,
    "py": 0.001, "ry": 0.001, "ty": 0.001, "wy": 0.001, "st": 0.001, "sp": 0.001, "sk": 0.001, "sm": 0.001, "sn": 0.001, "sw": 0.001, "sc": 0.001,
    "nn": 0.001, "mm": 0.001, "ll": 0.001, "rr": 0.001, "ss": 0.001, "tt": 0.001, "lt": 0.001, "rt": 0.001, "nd": 0.001, "nt": 0.001, "mp": 0.001, 
    "nk": 0.001, "ng": 0.001, "rk": 0.001
}

# Weighted probability of vowels and vowel combinations based on English lexicon
base_vowel_weights = {
    "a": 0.08, "e": 0.13, "i": 0.07, "o": 0.08, "u": 0.03,
}

vowel_weights = {
    "a": 0.08, "e": 0.13, "i": 0.07, "o": 0.08, "u": 0.03,
    "aa": 0.01, "ae": 0.01, "ai": 0.02, "ao": 0.01, "au": 0.01,
    "ea": 0.02, "ei": 0.02, "ee": 0.02, "eo": 0.01, "eu": 0.01,
    "ia": 0.01, "ie": 0.02, "ii": 0.01, "io": 0.02, "iu": 0.01,
    "oa": 0.01, "oe": 0.01, "oi": 0.02, "oo": 0.02, "ou": 0.02,
    "ua": 0.01, "ue": 0.01, "ui": 0.01, "uo": 0.01, "uu": 0.01
}

eng_town_suffixes = ["ton", "ville", "burg", "ford", "ham", "stead", "field", "wood", "dale", "port"]
eng_town_prefixes = ["New", "Central", "Upper", "Lower"]
eng_town_dist_suffixes = ["City", "Heights", "Haven", "Park", "Point"] # Non-geographical suffixes for districts

def generate_weighted(weights_dict):
    components = list(weights_dict.keys())
    weights = list(weights_dict.values())
    return random.choices(components, weights=weights)[0]

def generate_name_component(enable_extra_consonant=False, vowel_start=False):
    front_consonants = [generate_weighted(consonant_weights)]
    extra_consonant = random.choices([True, False], weights=[0.1, 0.9])[0] if enable_extra_consonant else False  # 10% chance to add an extra consonant
    return (random.choice(front_consonants) + \
           generate_weighted(vowel_weights) + \
           (generate_weighted(base_consonant_weights) if extra_consonant else "")) if not vowel_start else \
            (generate_weighted(base_vowel_weights) + \
            (generate_weighted(base_consonant_weights) if extra_consonant else ""))

def generate_town_name(suffix_prob=0.3, prefix_prob=0.2, geo_prob=0.2, vowel_start_prob=0.2, name_length_max=6, enable_dashes=True):
    name = ""
    if random.random() < suffix_prob:
        name_length = random.randint(1,2)
    
        for i in range(name_length):
            if i == 0 and random.random() < vowel_start_prob:
                name += generate_name_component(vowel_start=True)
            else:
                name += generate_name_component()
    
        name += random.choice(eng_town_suffixes)
    else:
        name_length = random.randint(2,name_length_max)
    
        for i in range(name_length-1):
            if i == 0 and random.random() < vowel_start_prob:
                name += generate_name_component(vowel_start=True)
            else:
                name += generate_name_component(enable_extra_consonant=True)

            if enable_dashes and name_length > 3 and i % 2 == 1:  # Add a dash after every two components for better flow
                if i < name_length - 2:  # Don't add a dash after the last component
                    name += "-"
        
        name += generate_name_component()  # Ensure the last component doesn't have an extra consonant for better flow

    name = name.capitalize()
    if random.random() < prefix_prob:
        name = random.choice(eng_town_prefixes) + " " + name

    if random.random() < geo_prob:
        name += " " + random.choice(eng_town_dist_suffixes)
    
    return name


class TownNameGenerator:
    def __init__(self, suffix_prob=0.3, prefix_prob=0.2, geo_prob=0.2, vowel_start_prob=0.2, name_length_max=6, enable_dashes=True):
        self.suffix_prob = suffix_prob
        self.prefix_prob = prefix_prob
        self.geo_prob = geo_prob
        self.vowel_start_prob = vowel_start_prob
        self.name_length_max = name_length_max
        self.enable_dashes = enable_dashes

    def generate_town_name(self):
        return generate_town_name(self.suffix_prob, self.prefix_prob, self.geo_prob, self.vowel_start_prob, self.name_length_max, self.enable_dashes)

# Example usage
if __name__ == "__main__":
    generator = TownNameGenerator()
    for _ in range(10):
        print(generator.generate_town_name())