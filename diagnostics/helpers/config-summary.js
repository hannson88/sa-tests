#!/usr/bin/env node
'use strict';

const path = require('path');

const configPath = path.resolve(process.argv[2] || '/opt/SentryAlert/config.js');

try {
  const config = require(configPath);
  const summary = {
    available: true,
    telegram: {
      tokenConfigured: Boolean(config.telegramAPIToken),
      chatIdConfigured: Boolean(config.telegramChatID),
    },
    board: config.board || null,
    storageRoot: config.dirRoot || null,
    temporaryRoot: config.dirTmp || null,
    logRoot: config.dirLog || null,
    viewCamViaMobileApp: Boolean(config.viewCamViaMobileApp),
    sendSentryAlert: config.sendSentryAlert !== false,
    sendEventMP4: Boolean(config.sendEventMP4),
    videoAnalysis: Boolean(config.videoAnalysis),
  };
  process.stdout.write(`${JSON.stringify(summary)}\n`);
} catch (error) {
  process.stderr.write(`Unable to read SentryAlert configuration: ${error.message}\n`);
  process.exitCode = 1;
}

