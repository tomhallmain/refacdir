import collections
from iptcinfo3 import IPTCInfo
import mimetypes
#import nltk
import os
import re
import sys


mimetypes.init()


class FileWithTags(object):
	disallowed_tags = [
		"a",
		"about",
		"above",
		"after",
		"again",
		"against",
		"aka",
		"all",
		"am",
		"an",
		"and",
		"any",
		"are",
		"as",
		"at",
		"be",
		"because",
		"been",
		"before",
		"being",
		"below",
		"between",
		"both",
		"but",
		"by",
		"can",
		"did",
		"do",
		"does",
		"doing",
		"don",
		"down",
		"during",
		"each",
		"et",
		"few",
		"for",
		"from",
		"further",
		"had",
		"has",
		"have",
		"having",
		"he",
		"here",
		"him",
		"himself",
		"how",
		"i",
		"if",
		"in",
		"into",
		"is",
		"it",
		"its",
		"itself",
		"just",
		"like",
		"me",
		"more",
		"most",
		"my",
		"myself",
		"no",
		"nor",
		"not",
		"now",
		"of",
		"off",
		"on",
		"once",
		"only",
		"or",
		"other",
		"our",
		"ours",
		"ourselves",
		"out",
		"over",
		"s",
		"same",
		"shas",
		"she",
		"should",
		"so",
		"some",
		"something",
		"such",
		"t",
		"than",
		"that",
		"the",
		"their",
		"theirs",
		"them",
		"themselves",
		"then",
		"there",
		"these",
		"they",
		"this",
		"those",
		"through",
		"to",
		"together",
		"too",
		"under",
		"until",
		"up",
		"very",
		"way",
		"was",
		"we",
		"were",
		"what",
		"when",
		"where",
		"which",
		"while",
		"who",
		"whom",
		"why",
		"will",
		"with",
		"you",
		"your",
		"yours",
		"yourself",
		"yourselves",
	]

	def __init__(self, file_path):
		self.file_path = file_path
		self.root, self.basename = os.path.split(file_path)
		_, self.extension = os.path.splitext(file_path)
		self.file_name = self.basename[0:len(self.basename)-len(self.extension)]

		if self.is_untaggable():
			self.taggable = False
			self.cleaned_name = None
			self.tags = set()
			return

		self.tags = self.gather_tags()
		# if len(self.tags) > 0 and "Wildflower" in self.file_name:
		# 	print(self.file_name)
		# 	print(str(self.tags))

	def is_media_type(self):
		mimestart = mimetypes.guess_type(self.basename)[0]
		if mimestart != None:
			mimestart = mimestart.split('/')[0]
			if mimestart in ['audio', 'video', 'image']:
				return True
		return False

	def is_untaggable(self):
		if len(self.file_name) < 1:
			return True
		if not re.search("^[a-z]", self.file_name):
			return True
		if " " in self.file_name and not "_" in self.file_name:
			return True
		return not self.is_media_type() # Only allow tagging on media type files for now.

	def gather_tags(self):
		tags = set()
		if "_" in self.file_name:
			tags_list = self.file_name.split("_")
		else:
			tags_list = [self.file_name]
		for tag in tags_list:
			if " " in tag or re.search("[^\\w]", tag) or re.search("[A-Z]", tag) or not re.search("^[a-z]", tag):
				break
			cleaned_tag = re.sub("[^a-z]", "", tag)
			if len(cleaned_tag) > 0 and cleaned_tag not in FileWithTags.disallowed_tags:
				tags.add(cleaned_tag)
		return tags

	def remove_tags(self, tags_to_remove):
		self.tags = self.tags - tags_to_remove

	def has_tags(self):
		return len(self.tags) > 0

	def apply_tags(self):
		info = IPTCInfo(self.file_path)
		current_tags = set(info["keywords"])
		if current_tags != self.tags:
			if len(current_tags) > 0:
				print(f"{self.file_path} existing tags were: {str(current_tags)}")
			tags_list = list(self.tags)
			tags_list.sort()
			info["keywords"] = tags_list
			info.save()
			os.remove(self.file_path + "~") # A lock file gets created by Windows OS on save but is not deleted by IPTCInfo3 module.
			#print(f"Set tags for {self.file_path}: {str(self.tags)}")


class TaggedFiles:
	def __init__(self, root_directory=".", min_tag_sparsity=2):
		self.files = []
		self.root_directory = root_directory
		self.min_tag_sparsity = min_tag_sparsity
		self.tags = collections.defaultdict(int)
		self.gather_tags()
		self.remove_sparse_tags()
		print(sorted(self.tags.keys()))

	def gather_tags(self):
		# Gather tags
		for root, dirs, files in os.walk(root_directory):
			for f in files:
				file_path = os.path.join(root, f)
				file_with_tags = FileWithTags(file_path)
				for tag in file_with_tags.tags:
					self.tags[tag] = self.tags[tag] + 1
				self.files.append(file_with_tags)

	def remove_sparse_tags(self):
		tags_to_remove = set()

		for tag in sorted(self.tags):
			if self.tags[tag] < self.min_tag_sparsity:
				tags_to_remove.add(tag)

		for tag in tags_to_remove:
			del self.tags[tag]

		for tag in sorted(self.tags):
			# if tag in nltk.corpus.stopwords.words():
			# 	print(f"{tag} (STOPWORD): {self.tags[tag]}")
			print(f"{tag}: {self.tags[tag]}")

		for file in self.files:
			if file.has_tags():
				file.remove_tags(tags_to_remove)

	def apply_tags_to_all(self):
		print("Applying tags to all media files in " + self.root_directory)
		for file in self.files:
			file.apply_tags()



if __name__ == "__main__":
	if len(sys.argv) < 2:
		print("Must provide root directory as first argument.")
		exit(1)
	root_directory = sys.argv[1]
	if not os.path.isdir(root_directory):
		print("First argument must be a valid directory.")
		exit(1)
	min_tag_sparsity = 2
	if len(sys.argv) > 2:
		min_tag_sparsity = int(sys.argv[2])
	files = TaggedFiles(root_directory=root_directory, min_tag_sparsity=min_tag_sparsity)
#	files.apply_tags_to_all()

