import setuptools
from re import search

with open("README.md", "r") as fh:
    long_description = fh.read()

with open("Whatsapp_Chat_Exporter/__init__.py", encoding="utf8") as f:
    version = search(r'__version__ = "(.*?)"', f.read()).group(1)

setuptools.setup(
    name="whatsapp-chat-exporter",
    version=version,
    author="KnugiHK",
    author_email="info@knugi.com",
    description="A Whatsapp database parser that will give you the "
                "history of your Whatsapp conversations in HTML and JSON.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/KnugiHK/Whatsapp-Chat-Exporter",
    packages=setuptools.find_packages(),
    package_data={
        '': ['whatsapp.html']
    },
    classifiers=[
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Communications :: Chat",
        "Topic :: Utilities",
        "Topic :: Database"
    ],
    python_requires='>=3.7',
    install_requires=[
       'jinja2',
       'bleach'
    ],
    extras_require={
        'android_backup':  ["pycryptodome", "javaobj-py3"],
        'crypt12':  ["pycryptodome"],
        'crypt12':  ["pycryptodome"],
        'crypt15':  ["pycryptodome", "javaobj-py3"]
    },
    entry_points={
        "console_scripts": [
            "wtsexporter = Whatsapp_Chat_Exporter.__main__:main"
        ]
    }
)
