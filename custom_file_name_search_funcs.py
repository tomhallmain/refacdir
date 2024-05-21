import os
import random
import re


# Add any custom filename search functions here to gather files for the BatchRenamers as set in the config YAML.


def random_selection(filename, chance=0.2):
    return random.random() <= chance

def is_id_filename(filename, fixed_length=22):
    file_basename = os.path.basename(filename)
    filename_part = file_basename.split(".")[0] if "." in file_basename else file_basename
    return is_id(filename_part, fixed_length=fixed_length)

def is_id(s, min_length=10, fixed_length=None):
    """
    Try to determine if a string appears to be a randomized ID following certain logic.
    """
    # Check if the string contains at least one lowercase letter, one uppercase letter, and one digit
    if (any(c.islower() for c in s) and any(c.isupper() for c in s)):
        # Check if the string does not contain any spaces or special characters
        if fixed_length is None:
            regex_string = "^[A-Za-z0-9_-]{" + str(min_length) + ",}$"
        else:
            regex_string = "^[A-Za-z0-9_-]{" + str(fixed_length) + "}$" 
        if re.search(regex_string, s):
            # Calculate the frequency of uppercase letters, lowercase letters, and digits
            upper_count = sum(1 for c in s if c.isupper())
            lower_count = sum(1 for c in s if c.islower())
            digit_count = sum(1 for c in s if c.isdigit())
            
            # Check if the frequency of uppercase letters is at least X% and not more than Y% of the total characters
            # Check if the frequency of lowercase letters is at least X% and not more than Y% of the total characters
            # Check if the frequency of digits is at least X% and not more than Y% of the total characters

            if (0.2 <= upper_count / len(s) <= 0.6 
                and 0.2 <= lower_count / len(s) <= 0.7):

                # Check to see if there are a lot of transitions
                transitions = 0

                for i in range(len(s) - 1):
                    c0 = s[i]
                    c1 = s[i+1]
                    if (c0.isupper() != c1.isupper()
                            or c0.isdigit() != c1.isdigit()
                            or c0.isalnum() != c1.isalnum()):
                        transitions += 1
#                        print(c0 + c1 + " < TRANSITION")
#                    else:
#                        print(c0 + c1)

                if transitions > len(s) / 3 or (transitions > len(s) / 4 and upper_count > len(s) / 4):
                    return True
                else:
                    print(f"transitions: {transitions}, length: {len(s)}")

    return False
