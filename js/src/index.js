const { loadConfig } = require("./config");

const {
    connect,
    getGliderId,
    subscribeToConnectionEvents
} = require("./sfmcClient");

async function main() {

    console.log("=================================");
    console.log("norgliders-data-pipeline Ingestion Service");
    console.log("=================================");

    const config = loadConfig();

    console.log("Loading configuration...");

    console.log("Connecting to SFMC...");

    const client = await connect();

    console.log("Connected.");

    for (const gliderName of config.sfmc.gliders) {

        const gliderId = await getGliderId(
            client.auth.token,
            gliderName
        );

        console.log(
            `Subscribing to ${gliderName} (${gliderId})`
        );

        subscribeToConnectionEvents(
            client.stompClient,
            gliderId,
            (events) => {
                console.log(gliderName);
                console.log(events);
            }
        );
    }

    console.log();
    console.log("Listening for configured gliders...");
}

main().catch((err) => {

    console.error();

    console.error("norgliders-data-pipeline failed to start.");

    console.error(err);

    process.exit(1);

});
