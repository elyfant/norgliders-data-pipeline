const fs = require("fs");
const path = require("path");

function loadJson(filename) {
    const filePath = path.join(
        __dirname,
        "..",
        "..",
        "config",
        filename
    );

    if (!fs.existsSync(filePath)) {
        throw new Error(
            `Missing configuration file: ${filePath}`
        );
    }

    return JSON.parse(
        fs.readFileSync(filePath, "utf8")
    );
}

function loadConfig() {

    const appConfig = loadJson("app.json");
    const sfmcServer = loadJson("sfmc.json");

    //
    // Validate application configuration
    //
    if (!appConfig.sfmc) {
        throw new Error(
            "Configuration error: missing sfmc section."
        );
    }

    if (!Array.isArray(appConfig.sfmc.gliders)) {
        throw new Error(
            "Configuration error: sfmc.gliders must be an array."
        );
    }

    if (appConfig.sfmc.gliders.length === 0) {
        throw new Error(
            "Configuration error: sfmc.gliders must contain at least one glider."
        );
    }

    //
    // Validate SFMC server configuration
    //
    if (!sfmcServer.host) {
        throw new Error(
            "Configuration error: missing SFMC host."
        );
    }

    if (!sfmcServer.apiCredentials) {
        throw new Error(
            "Configuration error: missing apiCredentials section."
        );
    }

    if (!sfmcServer.apiCredentials.clientId) {
        throw new Error(
            "Configuration error: missing SFMC clientId."
        );
    }

    if (!sfmcServer.apiCredentials.secret) {
        throw new Error(
            "Configuration error: missing SFMC secret."
        );
    }

    return {
        ...appConfig,
        sfmcServer
    };
}

module.exports = {
    loadConfig
};
