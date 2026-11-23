name: Bug Report
description: Create a report to help us improve
title: "[BUG]: "
labels: ["bug"]
assignees: []

body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to fill out this bug report! Please fill out the **Must have** environment details below so we can reproduce the issue.

  - type: input
    id: whatsapp-version
    attributes:
      label: WhatsApp Version
      description: What version of WhatsApp is the backup/data from?
      placeholder: e.g., 2.24.20.78
    validations:
      required: true

  - type: dropdown
    id: mobile-os
    attributes:
      label: Mobile OS
      description: Which mobile operating system is the WhatsApp data from?
      options:
        - Android
        - iOS
    validations:
      required: true

  - type: input
    id: mobile-os-version
    attributes:
      label: Mobile OS Version
      description: What version of Android or iOS is running on the device?
      placeholder: e.g., Android 14 / iOS 17.5
    validations:
      required: true

  - type: dropdown
    id: platform
    attributes:
      label: Host Platform
      description: Which operating system are you running the exporter on?
      options:
        - Linux
        - Windows
        - macOS
    validations:
      required: true

  - type: dropdown
    id: branch
    attributes:
      label: Exporter Branch
      description: Which branch are you using?
      options:
        - main
        - dev
    validations:
      required: true

  - type: input
    id: exporter-version
    attributes:
      label: Exporter Version
      description: Provide the version number or latest commit hash.
      placeholder: e.g., v0.10.0 or commit abc1234
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Describe the bug
      description: A clear and concise description of what the bug is.
    validations:
      required: true

  - type: textarea
    id: traceback
    attributes:
      label: Python Traceback
      description: If this is an error yielded by Python, paste the full traceback below.
      render: text
    validations:
      required: false

  - type: textarea
    id: reproduce
    attributes:
      label: Steps to Reproduce
      description: Steps to reproduce the behavior (Nice to have).
      value: |
        1. Go to '...'
        2. Click on '...'
        3. Scroll down to '...'
        4. See error
    validations:
      required: false

  - type: textarea
    id: context
    attributes:
      label: Screenshots & Additional Context
      description: Drag and drop screenshots here, or add any other context about the problem.
    validations:
      required: false
